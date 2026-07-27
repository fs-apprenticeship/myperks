import datetime
import json
import logging
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.schemas.dashboard import (
    BenefitsSummaryResponse,
    BenefitSummaryItemSchema,
    CreateRequestBody,
    LeaveBalanceSchema,
    RequestHistoryItemSchema,
    RequestHistoryResponse,
    VacationBalanceResponse,
)
from db.models import Employee, RequestHistory, VacationBalance
from db.session import get_session
from services.notifications import (
    dispatch,
    request_submitted,
    send_submission_receipt,
)

router = APIRouter(prefix="/me", tags=["dashboard"])

logger = logging.getLogger(__name__)

# Set False to send only HR-admin notifications, no submitter receipt.
_SEND_SUBMITTER_RECEIPT = True


# ── Shared helper ─────────────────────────────────────────────────────────────


async def _get_employee(clerk_user_id: str, db: AsyncSession) -> Employee:
    """
    Fetch the Employee row for the given Clerk user ID.
    """
    result = await db.execute(
        select(Employee).where(Employee.clerk_user_id == clerk_user_id)
    )
    employee = result.scalars().first()

    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    return employee


# ── GET /me/vacation ──────────────────────────────────────────────────────────


@router.get(
    "/vacation",
    response_model=VacationBalanceResponse,
    summary="Get current user's vacation balances",
)
async def get_vacation_balance(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> VacationBalanceResponse:
    """
    Returns the authenticated user's leave balances for the current year.
    """
    current_year = datetime.datetime.now().year
    employee = await _get_employee(clerk_user_id, db)

    result = await db.execute(
        select(VacationBalance).where(
            VacationBalance.employee_id == employee.id,
            VacationBalance.year == current_year,
        )
    )
    balances = result.scalars().all()

    return VacationBalanceResponse(
        year=current_year,
        balances=[
            LeaveBalanceSchema(
                leave_type=b.leave_type,
                total_days=b.total_days,
                used_days=b.used_days,
                remaining_days=b.remaining_days,
            )
            for b in balances
        ],
    )


# ── GET /me/requests ──────────────────────────────────────────────────────────


@router.get(
    "/requests",
    response_model=RequestHistoryResponse,
    summary="Get current user's paginated request history",
)
async def get_request_history(
    page: int = Query(default=1, ge=1, description="Page number, 1-indexed"),
    page_size: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> RequestHistoryResponse:
    """
    Returns the authenticated user's request history, newest first.
    Supports pagination via `page` and `page_size` query params.
    """
    employee = await _get_employee(clerk_user_id, db)

    # Count total matching rows for pagination metadata
    count_result = await db.execute(
        select(func.count()).where(  # pylint: disable=not-callable
            RequestHistory.employee_id == employee.id
        )
    )
    total = count_result.scalar() or 0

    # Fetch the current page of results
    offset = (page - 1) * page_size
    result = await db.execute(
        select(RequestHistory)
        .where(RequestHistory.employee_id == employee.id)
        .order_by(RequestHistory.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    requests = result.scalars().all()

    return RequestHistoryResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            RequestHistoryItemSchema(
                id=r.id,
                type=r.type,
                status=r.status,
                created_at=r.created_at.isoformat(),
                body=r.body,
            )
            for r in requests
        ],
    )


# ── POST /me/requests ─────────────────────────────────────────────────────────


@router.post(
    "/requests",
    response_model=RequestHistoryItemSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new HR request",
)
async def create_request(
    body: CreateRequestBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> RequestHistoryItemSchema:
    """
    Creates a new HR request (vacation, sick, PTO, or reimbursement) with status
    "pending". Called by the frontend after the user confirms the request in the chat.
    """
    employee = await _get_employee(clerk_user_id, db)
    # Read submitter fields before commit (avoids relying on expire_on_commit).
    submitter_name = cast(str, employee.name)
    submitter_email = cast(str, employee.email)

    new_request = RequestHistory(
        employee_id=employee.id,
        type=body.type,
        status="pending",
        body=json.dumps(body.body),
    )
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)

    # Best-effort: a notification failure must not affect the 201 response.
    request_id = cast(int, new_request.id)
    request_type = cast(str, new_request.type)
    try:
        await dispatch(
            background_tasks,
            db,
            request_submitted(
                request_id=request_id,
                request_type=request_type,
                submitter_name=submitter_name,
            ),
        )
        if _SEND_SUBMITTER_RECEIPT:
            send_submission_receipt(
                background_tasks,
                request_id=request_id,
                request_type=request_type,
                submitter_email=submitter_email,
                submitter_name=submitter_name,
            )
    except Exception:
        logger.exception(
            "Failed to dispatch submit notifications for request %s",
            request_id,
        )

    return RequestHistoryItemSchema(
        id=new_request.id,
        type=new_request.type,
        status=new_request.status,
        created_at=new_request.created_at.isoformat(),
        body=new_request.body,
    )


# ── GET /me/benefits-summary ──────────────────────────────────────────────────


@router.get(
    "/benefits-summary",
    response_model=BenefitsSummaryResponse,
    summary="Get aggregated benefits usage for dashboard charts",
)
async def get_benefits_summary(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> BenefitsSummaryResponse:
    """
    Returns aggregated benefits data shaped for frontend chart rendering.
    Includes percent_used per leave type calculated server-side.
    """

    current_year = datetime.datetime.now().year
    employee = await _get_employee(clerk_user_id, db)

    result = await db.execute(
        select(VacationBalance).where(
            VacationBalance.employee_id == employee.id,
            VacationBalance.year == current_year,
        )
    )
    balances = result.scalars().all()

    summary = []
    for b in balances:
        percent_used = (b.used_days / b.total_days * 100) if b.total_days > 0 else 0.0

        summary.append(
            BenefitSummaryItemSchema(
                leave_type=b.leave_type,
                total_days=b.total_days,
                used_days=b.used_days,
                remaining_days=b.remaining_days,
                percent_used=round(percent_used, 1),
            )
        )

    return BenefitsSummaryResponse(year=current_year, summary=summary)
