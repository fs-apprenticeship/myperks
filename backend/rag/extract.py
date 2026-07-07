"""
backend/rag/extract.py

LLM-based extraction of structured HR policy data from a document's chunks.

Given a document_id, reads all stored chunks and asks the LLM to return:
  {vacation_days, sick_days, pto_days, carryover_cap_days, proration_method, notes}

The caller owns DB commit — this function only flushes the DocumentExtraction row.
"""

from __future__ import annotations

import json
import logging

from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, DocumentChunk, DocumentExtraction
from settings import settings

logger = logging.getLogger(__name__)

_MAX_ANNUAL_DAYS = 365  # sanity bound for vacation/sick/pto day counts

_SYSTEM_PROMPT = """\
You are an HR policy analyst. You will be given text extracted from an HR document.
Extract the following information and return it as valid JSON with these exact keys:
  - vacation_days: annual vacation days (number, null if not found)
  - sick_days: annual sick/illness leave days (number, null if not found)
  - pto_days: annual PTO or personal days (number, null if not found)
  - carryover_cap_days: max unused vacation days that roll over to next year
      (number; null if the policy says carryover is unlimited/uncapped OR the
      document does not mention carryover, 0 if unused days are forfeited)
  - proration_method: how a mid-year hire's first-year allotment is computed
      ("monthly" if prorated by months worked, "none" if new hires get the full
      annual allotment regardless of start date, null if not stated)
  - notes: a plain-text summary of other relevant HR policies (string, max 300 chars)

Return ONLY the JSON object, no other text.
Example: {"vacation_days": 15, "sick_days": 10, "pto_days": 5, \
"carryover_cap_days": 5, "proration_method": "monthly", "notes": "..."}
"""


async def extract_document_policy(
    document_id: int,
    session: AsyncSession,
) -> DocumentExtraction:
    """
    Extract HR policy data from the given document's chunks using an LLM.

    Creates or updates the DocumentExtraction row for `document_id`.
    Sets status to 'extracting' during processing, then 'extracted' on success
    or 'failed' on error. Caller must commit.
    """
    extraction = await session.scalar(
        select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
    )
    if extraction is None:
        extraction = DocumentExtraction(document_id=document_id, status="extracting")
        session.add(extraction)
    else:
        extraction.status = "extracting"
        extraction.error_message = None  # type: ignore[assignment]

    await session.flush()

    try:
        doc = await session.scalar(select(Document).where(Document.id == document_id))
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        chunks = (
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )

        if not chunks:
            raise ValueError("Document has no chunks to extract from")

        combined_text = "\n\n".join(c.content for c in chunks)[:8000]

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,
            temperature=0,
            max_retries=2,
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"HR Document: {doc.filename}\n\n{combined_text}",
            },
        ]

        response = await llm.ainvoke(messages)
        raw = str(response.content).strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
            else:
                raise ValueError(f"LLM returned non-JSON: {raw[:200]}") from None

        rejected_fields: list[str] = []

        def _days_or_none(field: str, v: object) -> float | None:
            try:
                value = float(v) if v is not None else None  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            # Annual leave days can't be negative or exceed a year — an LLM
            # hallucination here would otherwise flow straight into HR's
            # review queue looking like a plausible real value.
            if value is not None and not (0 <= value <= _MAX_ANNUAL_DAYS):
                rejected_fields.append(field)
                return None
            return value

        def _carryover_or_none(v: object) -> float | None:
            # null is meaningful here (uncapped/unspecified carryover), so we
            # only coerce real numbers and drop anything out of range.
            try:
                value = float(v) if v is not None else None  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            if value is not None and not (0 <= value <= _MAX_ANNUAL_DAYS):
                rejected_fields.append("carryover_cap_days")
                return None
            return value

        def _proration_or_none(v: object) -> str | None:
            # Only the two values the seeding function understands survive;
            # anything else falls back to the company default downstream.
            return str(v) if v in ("monthly", "none") else None

        extracted: dict[str, object] = {
            "vacation_days": _days_or_none(
                "vacation_days", parsed.get("vacation_days")
            ),
            "sick_days": _days_or_none("sick_days", parsed.get("sick_days")),
            "pto_days": _days_or_none("pto_days", parsed.get("pto_days")),
            "carryover_cap_days": _carryover_or_none(parsed.get("carryover_cap_days")),
            "proration_method": _proration_or_none(parsed.get("proration_method")),
            "notes": str(parsed.get("notes", ""))[:300],
        }

        if rejected_fields:
            # Surface the rejection to the HR reviewer instead of silently
            # leaving the field blank with no explanation.
            extracted["notes"] = (
                f"[needs manual review: {', '.join(rejected_fields)} out of range "
                f"in source document] {extracted['notes']}"
            )[:300]
            logger.warning(
                "Rejected out-of-range fields for document_id=%d: %s",
                document_id,
                rejected_fields,
            )

        extraction.extracted_data = json.dumps(extracted)  # type: ignore[assignment]
        extraction.status = "extracted"
        logger.info("Extraction complete document_id=%d", document_id)

    except Exception as exc:
        logger.exception("Extraction failed for document_id=%d: %s", document_id, exc)
        extraction.status = "failed"
        extraction.error_message = str(exc)[:500]  # type: ignore[assignment]

    await session.flush()
    return extraction
