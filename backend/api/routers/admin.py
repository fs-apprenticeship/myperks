# backend/api/routers/admin.py
"""
Single admin endpoint: approve or reject an employee HR request.
Behind require_admin — only HR admins may call this.
Approving a leave request updates VacationBalance.used_days so the
employee's dashboard balance reflects the change immediately.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from math import ceil
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import require_admin
from api.schemas.admin import (
    ApproveExtractionBody,
    ApproveExtractionResponse,
    ApproveRejectBody,
    ApproveRejectResponse,
    BalanceSnapshot,
    DepartmentBalanceItem,
    DepartmentBalancesResponse,
    DepartmentPoliciesResponse,
    DepartmentPolicyItem,
    DocumentExtractionResponse,
    EmployeeDetail,
    EmployeeListItem,
    ExtractionData,
    PaginatedEmployees,
    PaginatedRequests,
    PatchEmployeeBody,
    PatchEmployeeResponse,
    PreCreateEmployeeBody,
    PreCreateEmployeeResponse,
    RequestHistorySnapshot,
    RequestListItem,
)
from db.models import (
    Document,
    DocumentExtraction,
    Employee,
    RequestHistory,
    VacationBalance,
)
from db.session import get_session
from rag.extract import extract_document_policy
from services.vacation import seed_employee_vacation_balances

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/employees",
    response_model=PaginatedEmployees,
    summary="List all employees (paginated, searchable)",
)
async def list_employees(
    page: int = 1,
    size: int = 10,
    q: str | None = None,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> PaginatedEmployees:
    if size < 1:
        size = 1
    if size > 100:
        size = 100
    if page < 1:
        page = 1

    base_query = select(Employee)
    count_query = select(func.count()).select_from(Employee)

    if q:
        pattern = f"%{q}%"
        filter_clause = or_(
            Employee.name.ilike(pattern),
            Employee.email.ilike(pattern),
        )
        base_query = base_query.where(filter_clause)
        count_query = count_query.where(filter_clause)

    total: int = cast(int, await db.scalar(count_query)) or 0

    rows = (
        (
            await db.execute(
                base_query.order_by(Employee.name).offset((page - 1) * size).limit(size)
            )
        )
        .scalars()
        .all()
    )

    return PaginatedEmployees(
        items=[
            EmployeeListItem(
                id=cast(int, e.id),
                name=e.name,
                email=e.email,
                department=e.department,
                role=e.role,
                joined_date=e.joined_date,
                linked=e.clerk_user_id is not None,
            )
            for e in rows
        ],
        total=total,
        page=page,
        size=size,
        pages=ceil(total / size) if total else 0,
    )


@router.get(
    "/employees/{employee_id}",
    response_model=EmployeeDetail,
    summary="Get a single employee with balances and request history",
)
async def get_employee_detail(
    employee_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> EmployeeDetail:
    emp = (
        await db.execute(
            select(Employee)
            .options(
                selectinload(Employee.vacation_balances),
                selectinload(Employee.request_histories),
            )
            .where(Employee.id == employee_id)
        )
    ).scalar_one_or_none()

    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    return EmployeeDetail(
        id=cast(int, emp.id),
        name=emp.name,
        email=emp.email,
        department=emp.department,
        role=emp.role,
        joined_date=emp.joined_date,
        benefits_year_reset=emp.benefits_year_reset,
        linked=emp.clerk_user_id is not None,
        balances=[
            BalanceSnapshot(
                leave_type=b.leave_type,
                total_days=b.total_days,
                used_days=b.used_days,
                remaining_days=b.remaining_days,
            )
            for b in emp.vacation_balances
        ],
        request_history=[
            RequestHistorySnapshot(
                id=cast(int, r.id),
                type=cast(str, r.type),
                status=cast(str, r.status),
                created_at=r.created_at,
                body=cast(str | None, r.body),
            )
            for r in sorted(
                emp.request_histories, key=lambda r: r.created_at, reverse=True
            )
        ],
    )


@router.post(
    "/employees",
    response_model=PreCreateEmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pre-create an employee row (no Clerk account yet)",
)
async def pre_create_employee(
    body: PreCreateEmployeeBody,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> PreCreateEmployeeResponse:
    # Reject duplicate email
    existing = (
        await db.execute(select(Employee).where(Employee.email == body.email))
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An employee with this email already exists",
        )

    # Require an approved HR policy for the department before adding anyone
    # to it, so the employee's vacation balance is always backed by a real
    # policy document instead of silently falling back to company defaults.
    has_approved_policy = await db.scalar(
        select(DocumentExtraction.id)
        .join(Document, Document.id == DocumentExtraction.document_id)
        .where(
            Document.department == body.department,
            DocumentExtraction.status == "approved",
        )
        .limit(1)
    )
    if has_approved_policy is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No approved HR policy found for the {body.department!r} "
                "department. Upload and approve a policy document for this "
                "department before adding employees to it."
            ),
        )

    emp = Employee(
        clerk_user_id=None,
        name=body.name,
        email=body.email,
        department=body.department,
        role="employee",
        joined_date=body.joined_date,
        benefits_year_reset=body.benefits_year_reset,
    )
    db.add(emp)
    await db.flush()

    # Seed this year's vacation balances from the department's approved
    # policy, prorated by joined_date (T46).
    await seed_employee_vacation_balances(
        db, cast(int, emp.id), emp.department, emp.joined_date.year, emp.joined_date
    )

    await db.commit()
    await db.refresh(emp)

    return PreCreateEmployeeResponse(
        id=cast(int, emp.id),
        name=emp.name,
        email=emp.email,
        department=emp.department,
        role=emp.role,
        joined_date=emp.joined_date,
        benefits_year_reset=emp.benefits_year_reset,
        linked=False,
    )


@router.patch(
    "/employees/{employee_id}",
    response_model=PatchEmployeeResponse,
    summary="Update an employee's department or role",
)
async def patch_employee(
    employee_id: int,
    body: PatchEmployeeBody,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> PatchEmployeeResponse:
    emp = (
        await db.execute(select(Employee).where(Employee.id == employee_id))
    ).scalar_one_or_none()

    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if body.department is not None:
        emp.department = body.department
    if body.role is not None:
        emp.role = body.role

    await db.commit()
    await db.refresh(emp)

    return PatchEmployeeResponse(
        id=cast(int, emp.id),
        name=emp.name,
        email=emp.email,
        department=emp.department,
        role=emp.role,
        joined_date=emp.joined_date,
        benefits_year_reset=emp.benefits_year_reset,
        linked=emp.clerk_user_id is not None,
    )


@router.get(
    "/requests",
    response_model=PaginatedRequests,
    summary="List all requests across employees (filterable, paginated, newest first)",
)
async def list_requests(
    page: int = 1,
    size: int = 10,
    status_filter: str | None = "pending",
    employee_id: int | None = None,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> PaginatedRequests:
    if size < 1:
        size = 1
    if size > 100:
        size = 100
    if page < 1:
        page = 1

    base_query = select(RequestHistory, Employee.name.label("employee_name")).join(
        Employee, Employee.id == RequestHistory.employee_id
    )
    count_query = (
        select(func.count())
        .select_from(RequestHistory)
        .join(Employee, Employee.id == RequestHistory.employee_id)
    )

    if status_filter is not None and status_filter != "":
        base_query = base_query.where(RequestHistory.status == status_filter)
        count_query = count_query.where(RequestHistory.status == status_filter)

    if employee_id is not None:
        base_query = base_query.where(RequestHistory.employee_id == employee_id)
        count_query = count_query.where(RequestHistory.employee_id == employee_id)

    total: int = cast(int, await db.scalar(count_query)) or 0

    rows = (
        await db.execute(
            base_query.order_by(RequestHistory.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()

    return PaginatedRequests(
        items=[
            RequestListItem(
                id=cast(int, r.RequestHistory.id),
                employee_id=cast(int, r.RequestHistory.employee_id),
                employee_name=cast(str, r.employee_name),
                type=cast(str, r.RequestHistory.type),
                status=cast(str, r.RequestHistory.status),
                created_at=r.RequestHistory.created_at,
                body=cast(str | None, r.RequestHistory.body),
            )
            for r in rows
        ],
        total=total,
        page=page,
        size=size,
        pages=ceil(total / size) if total else 0,
    )


@router.patch(
    "/requests/{request_id}",
    response_model=ApproveRejectResponse,
    summary="Approve or reject an employee HR request",
)
async def approve_or_reject_request(
    request_id: int,
    body: ApproveRejectBody,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> ApproveRejectResponse:
    req = (
        await db.execute(select(RequestHistory).where(RequestHistory.id == request_id))
    ).scalar_one_or_none()

    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is already '{req.status}'",
        )

    emp = (
        await db.execute(select(Employee).where(Employee.id == req.employee_id))
    ).scalar_one_or_none()

    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )

    req_body: dict[str, object] = json.loads(cast(str, req.body)) if req.body else {}

    # On approval of a leave type — deduct days from the balance
    if body.status == "approved" and req.type in ("vacation", "sick", "pto"):
        days = float(cast(float, req_body.get("days", 0)))
        start_date_str = str(req_body.get("start_date", ""))
        try:
            year = (
                datetime.fromisoformat(start_date_str).year
                if start_date_str
                else datetime.now(UTC).year
            )
        except ValueError:
            year = datetime.now(UTC).year

        if days > 0:
            balance = (
                await db.execute(
                    select(VacationBalance).where(
                        VacationBalance.employee_id == req.employee_id,
                        VacationBalance.leave_type == req.type,
                        VacationBalance.year == year,
                    )
                )
            ).scalar_one_or_none()

            if balance is not None:
                balance.used_days += days

    # Store rejection reason inside the request body
    if body.status == "rejected" and body.rejection_reason:
        req_body["rejection_reason"] = body.rejection_reason
        req.body = json.dumps(req_body)  # type: ignore[assignment]

    req.status = body.status
    await db.commit()

    # Fetch updated balances to return in response
    current_year = datetime.now(UTC).year
    balances = (
        (
            await db.execute(
                select(VacationBalance).where(
                    VacationBalance.employee_id == req.employee_id,
                    VacationBalance.year == current_year,
                )
            )
        )
        .scalars()
        .all()
    )

    return ApproveRejectResponse(
        request_id=cast(int, req.id),
        employee_name=cast(str, emp.name),
        employee_email=cast(str, emp.email),
        request_type=cast(str, req.type),
        new_status=body.status,
        rejection_reason=body.rejection_reason,
        updated_balances=[
            BalanceSnapshot(
                leave_type=b.leave_type,
                total_days=b.total_days,
                used_days=b.used_days,
                remaining_days=b.remaining_days,
            )
            for b in balances
        ],
    )


# ── Document extraction endpoints ─────────────────────────────────────────────


def _parse_extraction_data(raw: str | None) -> ExtractionData | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return ExtractionData(
            vacation_days=d.get("vacation_days"),
            sick_days=d.get("sick_days"),
            pto_days=d.get("pto_days"),
            carryover_cap_days=d.get("carryover_cap_days"),
            proration_method=d.get("proration_method"),
            notes=str(d.get("notes", "")),
        )
    except Exception:
        return None


@router.post(
    "/documents/{document_id}/extract",
    response_model=DocumentExtractionResponse,
    summary="Trigger LLM extraction of HR policy data from a document",
)
async def trigger_extraction(
    document_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> DocumentExtractionResponse:
    doc = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    existing = (
        await db.execute(
            select(DocumentExtraction).where(
                DocumentExtraction.document_id == document_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "extracting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Extraction is already in progress for this document.",
        )

    extraction = await extract_document_policy(document_id=document_id, session=db)
    await db.commit()

    return DocumentExtractionResponse(
        id=cast(int, extraction.id),
        document_id=cast(int, extraction.document_id),
        status=extraction.status,
        extracted_data=_parse_extraction_data(
            cast(str | None, extraction.extracted_data)
        ),
        approved_data=_parse_extraction_data(
            cast(str | None, extraction.approved_data)
        ),
        reviewed_at=extraction.reviewed_at,
        error_message=cast(str | None, extraction.error_message),
    )


@router.get(
    "/documents/{document_id}/extraction",
    response_model=DocumentExtractionResponse | None,
    summary="Get the extraction result for a document",
)
async def get_extraction(
    document_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> DocumentExtractionResponse | None:
    extraction = (
        await db.execute(
            select(DocumentExtraction).where(
                DocumentExtraction.document_id == document_id
            )
        )
    ).scalar_one_or_none()

    if extraction is None:
        return None

    return DocumentExtractionResponse(
        id=cast(int, extraction.id),
        document_id=cast(int, extraction.document_id),
        status=extraction.status,
        extracted_data=_parse_extraction_data(
            cast(str | None, extraction.extracted_data)
        ),
        approved_data=_parse_extraction_data(
            cast(str | None, extraction.approved_data)
        ),
        reviewed_at=extraction.reviewed_at,
        error_message=cast(str | None, extraction.error_message),
    )


@router.post(
    "/documents/{document_id}/extraction/approve",
    response_model=ApproveExtractionResponse,
    summary="Approve extraction data and apply it to department employees",
)
async def approve_extraction(
    document_id: int,
    body: ApproveExtractionBody,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    admin: Employee = Depends(require_admin),  # noqa: B008
) -> ApproveExtractionResponse:
    doc = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    extraction = (
        await db.execute(
            select(DocumentExtraction).where(
                DocumentExtraction.document_id == document_id
            )
        )
    ).scalar_one_or_none()
    if extraction is None or extraction.status not in (
        "extracted",
        "approved",
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document must be extracted before approving. Run extraction first.",
        )

    # Persist approval. carryover_cap_days / proration_method are read back by
    # services.vacation.seed_employee_vacation_balances (T46).
    approved: dict[str, object] = {
        "vacation_days": body.vacation_days,
        "sick_days": body.sick_days,
        "pto_days": body.pto_days,
        "carryover_cap_days": body.carryover_cap_days,
        "proration_method": body.proration_method,
        "notes": body.notes,
    }
    extraction.approved_data = json.dumps(approved)  # type: ignore[assignment]
    extraction.status = "approved"
    extraction.reviewed_by = cast(int, admin.id)  # type: ignore[assignment]
    extraction.reviewed_at = datetime.now(UTC)  # type: ignore[assignment]

    # Apply policy to all employees in the document's department
    department = doc.department
    leave_map = {
        "vacation": body.vacation_days,
        "sick": body.sick_days,
        "pto": body.pto_days,
    }

    employees = (
        (await db.execute(select(Employee).where(Employee.department == department)))
        .scalars()
        .all()
    )

    employee_ids = [cast(int, emp.id) for emp in employees]
    active_leave_types = [lt for lt, days in leave_map.items() if days is not None]

    existing_balances: dict[tuple[int, str], VacationBalance] = {}
    if employee_ids and active_leave_types:
        balance_rows = (
            (
                await db.execute(
                    select(VacationBalance).where(
                        VacationBalance.employee_id.in_(employee_ids),
                        VacationBalance.leave_type.in_(active_leave_types),
                        VacationBalance.year == body.year,
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_balances = {
            (cast(int, b.employee_id), b.leave_type): b for b in balance_rows
        }

    updated = 0
    for emp in employees:
        for leave_type, total_days in leave_map.items():
            if total_days is None:
                continue
            key = (cast(int, emp.id), leave_type)
            balance = existing_balances.get(key)
            if balance is not None:
                balance.total_days = total_days
                # A lower total than what's already been used would otherwise
                # drive remaining_days (total_days - used_days) negative.
                balance.used_days = min(balance.used_days, total_days)
            else:
                db.add(
                    VacationBalance(
                        employee_id=cast(int, emp.id),
                        leave_type=leave_type,
                        total_days=total_days,
                        used_days=0.0,
                        year=body.year,
                    )
                )
        updated += 1

    await db.commit()

    warning = (
        f"No employees found in department {department!r} — "
        "this policy will only apply to employees added from now on."
        if updated == 0
        else None
    )

    return ApproveExtractionResponse(
        extraction_id=cast(int, extraction.id),
        document_id=document_id,
        department=department,
        year=body.year,
        employees_updated=updated,
        warning=warning,
    )


@router.get(
    "/departments/policies",
    response_model=DepartmentPoliciesResponse,
    summary="Latest approved HR policy per department",
)
async def get_department_policies(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> DepartmentPoliciesResponse:
    # Latest approved extraction per department (one row per dept)
    rows = (
        await db.execute(
            select(DocumentExtraction, Document.department)
            .join(Document, Document.id == DocumentExtraction.document_id)
            .where(DocumentExtraction.status == "approved")
            .order_by(
                Document.department,
                DocumentExtraction.reviewed_at.desc(),
            )
        )
    ).all()

    # Keep only the most-recent approved extraction per department
    seen: set[str] = set()
    policies: list[DepartmentPolicyItem] = []
    for row in rows:
        dept = cast(str, row.department)
        if dept in seen:
            continue
        seen.add(dept)
        ext = row.DocumentExtraction
        data: dict[str, object] = (
            json.loads(cast(str, ext.approved_data)) if ext.approved_data else {}
        )

        def _f(v: object) -> float | None:
            try:
                return float(v) if v is not None else None  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        policies.append(
            DepartmentPolicyItem(
                department=dept,
                document_id=cast(int, ext.document_id),
                vacation_days=_f(data.get("vacation_days")),
                sick_days=_f(data.get("sick_days")),
                pto_days=_f(data.get("pto_days")),
                notes=str(data.get("notes", "")),
                approved_at=cast(datetime, ext.reviewed_at),
            )
        )

    return DepartmentPoliciesResponse(policies=policies)


@router.get(
    "/departments/balances",
    response_model=DepartmentBalancesResponse,
    summary="Vacation balances aggregated per department for a given year",
)
async def get_department_balances(
    year: int | None = None,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    _admin: Employee = Depends(require_admin),  # noqa: B008
) -> DepartmentBalancesResponse:
    target_year = year or date.today().year

    # Derive balances from VacationBalance rows for the requested year, not from
    # DocumentExtraction.approved_data — that row is 1:1 with the document and
    # gets overwritten on every re-approval, so it has no year dimension and
    # can't answer "what was approved for year X" once a later year exists.
    # VacationBalance rows, by contrast, are written per-year by approve_extraction
    # and never overwritten across years, so they're the only source that's
    # actually scoped to `target_year`.
    rows = (
        await db.execute(
            select(
                Employee.department,
                VacationBalance.leave_type,
                VacationBalance.employee_id,
                VacationBalance.total_days,
            )
            .join(VacationBalance, VacationBalance.employee_id == Employee.id)
            .where(VacationBalance.year == target_year)
        )
    ).all()

    if not rows:
        return DepartmentBalancesResponse(year=target_year, departments=[])

    dept_employees: dict[str, set[int]] = defaultdict(set)
    dept_leave_totals: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        dept = cast(str, row.department)
        dept_employees[dept].add(cast(int, row.employee_id))
        dept_leave_totals[dept][row.leave_type].append(float(row.total_days))

    def _avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    departments = [
        DepartmentBalanceItem(
            department=dept,
            employee_count=len(dept_employees[dept]),
            vacation_days=_avg(dept_leave_totals[dept].get("vacation", [])),
            sick_days=_avg(dept_leave_totals[dept].get("sick", [])),
            pto_days=_avg(dept_leave_totals[dept].get("pto", [])),
        )
        for dept in sorted(dept_employees)
    ]

    return DepartmentBalancesResponse(year=target_year, departments=departments)
