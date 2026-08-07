import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from api.schemas.notifications import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationItem,
    NotificationListResponse,
    NotificationsMeta,
)
from db.models import Employee, Notification
from db.session import get_session

router = APIRouter(prefix="/me", tags=["notifications"])


async def _get_employee(clerk_user_id: str, db: AsyncSession) -> Employee:
    """Fetch the Employee row for the caller's Clerk user ID (mirrors dashboard)."""
    result = await db.execute(
        select(Employee).where(Employee.clerk_user_id == clerk_user_id)
    )
    employee = result.scalars().first()
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found"
        )
    return employee


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="List the caller's notifications",
)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> NotificationListResponse:
    employee = await _get_employee(clerk_user_id, db)
    me = cast(int, employee.id)

    # Both counts in one round trip; FILTER narrows the unread tally without a
    # second scan of the same rows.
    total, unread_count = (
        await db.execute(
            select(
                func.count(Notification.id),
                func.count(Notification.id).filter(Notification.read_at.is_(None)),
            ).where(Notification.recipient_id == me)
        )
    ).one()

    rows = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.recipient_id == me)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return NotificationListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[NotificationItem.model_validate(row) for row in rows],
        meta=NotificationsMeta(unread_count=unread_count),
    )


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="Mark one notification read",
)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> MarkReadResponse:
    employee = await _get_employee(clerk_user_id, db)
    me = cast(int, employee.id)

    # Scope by BOTH id and recipient: a non-owner gets a 404 indistinguishable
    # from a missing row (doesn't leak that the id exists).
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_id == me,
            )
        )
    ).scalar_one_or_none()

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )

    if notification.read_at is None:
        notification.read_at = datetime.datetime.now(datetime.UTC)
    await db.commit()

    return MarkReadResponse(
        id=cast(int, notification.id),
        read_at=cast(datetime.datetime, notification.read_at),
    )


@router.patch(
    "/notifications/read-all",
    response_model=MarkAllReadResponse,
    summary="Mark all the caller's notifications read",
)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_session),  # noqa: B008
    clerk_user_id: str = Depends(get_current_user),  # noqa: B008
) -> MarkAllReadResponse:
    employee = await _get_employee(clerk_user_id, db)
    me = cast(int, employee.id)

    result = await db.execute(
        update(Notification)
        .where(Notification.recipient_id == me, Notification.read_at.is_(None))
        .values(read_at=datetime.datetime.now(datetime.UTC))
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    return MarkAllReadResponse(updated=result.rowcount)
