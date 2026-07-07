"""
myPerks — Vacation balance seeding: proration + capped carryover (T46)
backend/services/vacation.py

Single source of truth for how many leave days an employee starts a year
with. Called when an employee is created (current year) and by the
year-boundary rollover job (services/rollover.py).

Two rules combine to produce a leave type's total_days for a year:

1. **Mid-year-hire proration** — someone hired during the target year earns a
   fraction of the annual allotment, based on months remaining in the year
   (hire month counts as worked). Governed by the department policy's
   ``proration_method`` ("monthly" prorates, "none" grants the full amount
   regardless of start date); defaults to "monthly" when unset.
2. **Capped carryover** — unused days from the employee's balance in the
   prior year roll into the new year, capped at the policy's
   ``carryover_cap_days`` (absent key -> default cap; null -> uncapped).
   Only vacation carries over by default.

Both the day allotments and the carryover cap can be overridden by the
department's most recently approved policy document; absent values fall back
to the company defaults below.
"""

from __future__ import annotations

import datetime
import json
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Document, DocumentExtraction, VacationBalance

# (leave_type, default annual allotment, default carryover cap)
# Only vacation carries over unused days by default.
_LEAVE_TYPE_DEFAULTS: tuple[tuple[str, float, float], ...] = (
    ("vacation", 15.0, 5.0),
    ("sick", 10.0, 0.0),
    ("pto", 5.0, 0.0),
)


async def _get_approved_policy(
    session: AsyncSession, department: str
) -> dict[str, object]:
    """The department's most recently approved policy, or {} if none exists."""
    extraction = await session.scalar(
        select(DocumentExtraction)
        .join(Document, Document.id == DocumentExtraction.document_id)
        .where(
            Document.department == department,
            DocumentExtraction.status == "approved",
        )
        .order_by(DocumentExtraction.reviewed_at.desc())
        .limit(1)
    )
    if extraction is None or not extraction.approved_data:
        return {}
    return cast("dict[str, object]", json.loads(str(extraction.approved_data)))


def _months_remaining(joined_date: datetime.date | None, year: int) -> int:
    """Months of `year` worked, counting the hire month. Full 12 if hired earlier."""
    if joined_date is not None and joined_date.year == year:
        return 12 - joined_date.month + 1
    return 12


async def _prior_year_remaining(
    session: AsyncSession, employee_id: int, leave_type: str, prior_year: int
) -> float | None:
    balance = await session.scalar(
        select(VacationBalance).where(
            VacationBalance.employee_id == employee_id,
            VacationBalance.leave_type == leave_type,
            VacationBalance.year == prior_year,
        )
    )
    if balance is None:
        return None
    return balance.total_days - balance.used_days


async def seed_employee_vacation_balances(
    session: AsyncSession,
    employee_id: int,
    department: str,
    year: int,
    joined_date: datetime.date | None,
) -> int:
    """
    Create `year`'s VacationBalance rows for `employee_id`, prorating mid-year
    hires and carrying over capped unused days from `year - 1`. Skips leave
    types that already have a row for the year (idempotent — safe to call
    from both employee creation and the rollover job for the same year).

    Returns the number of rows created.
    """
    policy = await _get_approved_policy(session, department)
    proration_method = policy.get("proration_method") or "monthly"
    months_remaining = _months_remaining(joined_date, year)
    cap_specified = "carryover_cap_days" in policy

    existing_types = set(
        (
            await session.scalars(
                select(VacationBalance.leave_type).where(
                    VacationBalance.employee_id == employee_id,
                    VacationBalance.year == year,
                )
            )
        ).all()
    )

    created: list[VacationBalance] = []
    for leave_type, default_days, default_cap in _LEAVE_TYPE_DEFAULTS:
        if leave_type in existing_types:
            continue

        policy_days = cast("float | None", policy.get(f"{leave_type}_days"))
        base = float(policy_days or default_days)
        if proration_method == "monthly":
            base = round(base * months_remaining / 12 * 2) / 2

        cap: float | None
        if leave_type == "vacation" and cap_specified:
            # None means uncapped here, distinct from the key being absent.
            cap = cast("float | None", policy.get("carryover_cap_days"))
        else:
            cap = default_cap

        prior_remaining = await _prior_year_remaining(
            session, employee_id, leave_type, year - 1
        )
        carry = 0.0
        if prior_remaining and prior_remaining > 0:
            carry = prior_remaining if cap is None else min(prior_remaining, cap)

        created.append(
            VacationBalance(
                employee_id=employee_id,
                leave_type=leave_type,
                total_days=base + carry,
                used_days=0.0,
                year=year,
            )
        )

    if created:
        session.add_all(created)
        await session.flush()
    return len(created)
