from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Employee, RequestHistory
from services.email import send_email
from settings import settings

logger = logging.getLogger(__name__)


class NotificationKind(StrEnum):
    REQUEST_SUBMITTED = "request_submitted"
    REQUEST_STATUS_CHANGED = "request_status_changed"


@dataclass(frozen=True)
class NotificationEvent:
    """What happened, plus the context needed to render its message.

    Only the context fields relevant to ``kind`` are populated; the builders
    below enforce that pairing.
    """

    kind: NotificationKind
    request_id: int
    request_type: str
    submitter_name: str | None = None  # REQUEST_SUBMITTED
    new_status: str | None = None  # REQUEST_STATUS_CHANGED
    rejection_reason: str | None = None  # REQUEST_STATUS_CHANGED (optional)


@dataclass(frozen=True)
class Recipient:
    """Plain recipient data, deliberately not an ORM object."""

    id: int
    email: str
    name: str


def request_submitted(
    *, request_id: int, request_type: str, submitter_name: str
) -> NotificationEvent:
    """Build the event for a newly submitted request (notifies HR admins)."""
    return NotificationEvent(
        kind=NotificationKind.REQUEST_SUBMITTED,
        request_id=request_id,
        request_type=request_type,
        submitter_name=submitter_name,
    )


def request_status_changed(
    *,
    request_id: int,
    request_type: str,
    new_status: str,
    rejection_reason: str | None = None,
) -> NotificationEvent:
    """Build the event for an approved/rejected request (notifies the submitter)."""
    return NotificationEvent(
        kind=NotificationKind.REQUEST_STATUS_CHANGED,
        request_id=request_id,
        request_type=request_type,
        new_status=new_status,
        rejection_reason=rejection_reason,
    )


def _to_recipient(employee: Employee) -> Recipient:
    return Recipient(
        id=cast(int, employee.id),
        email=cast(str, employee.email),
        name=cast(str, employee.name),
    )


async def resolve_recipients(
    db: AsyncSession, event: NotificationEvent
) -> list[Recipient]:
    """Return who should be notified for ``event``, as plain data.

    Runs in-request so the DB work happens while the session is live.
    """
    if event.kind is NotificationKind.REQUEST_SUBMITTED:
        # Every HR admin, for now.
        # joining the department off the request's employee and filtering here.
        employees = (
            await db.scalars(select(Employee).where(Employee.role == "hr_admin"))
        ).all()
        return [_to_recipient(employee) for employee in employees]

    # REQUEST_STATUS_CHANGED: notify the employee who submitted the request.
    request = (
        await db.execute(
            select(RequestHistory).where(RequestHistory.id == event.request_id)
        )
    ).scalar_one_or_none()
    if request is None:
        return []
    submitter = (
        await db.execute(select(Employee).where(Employee.id == request.employee_id))
    ).scalar_one_or_none()
    if submitter is None:
        return []
    return [_to_recipient(submitter)]


def _render(event: NotificationEvent) -> tuple[str, str]:
    """Return the (subject, body) plain-text copy for ``event``."""
    if event.kind is NotificationKind.REQUEST_SUBMITTED:
        subject = f"New {event.request_type} request from {event.submitter_name}"
        body = (
            f"{event.submitter_name} submitted a {event.request_type} request "
            f"(#{event.request_id}). Review it in the admin dashboard."
        )
        return subject, body

    subject = f"Your {event.request_type} request was {event.new_status}"
    body = (
        f"Your {event.request_type} request (#{event.request_id}) "
        f"was {event.new_status}."
    )
    if event.rejection_reason:
        body += f" Reason: {event.rejection_reason}"
    return subject, body


async def dispatch(
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    event: NotificationEvent,
) -> None:
    """Resolve recipients in-request, then queue one email per recipient.

    The email send is a background task so it never blocks or fails the request.
    Enqueues only when email notifications are enabled; ``send_email`` is itself
    a no-op when disabled, so this is a second, cheaper guard.
    """
    recipients = await resolve_recipients(db, event)
    if not settings.notifications_email_enabled:
        return

    subject, body = _render(event)
    for recipient in recipients:
        background_tasks.add_task(
            send_email,
            to=recipient.email,
            subject=subject,
            body=body,
        )

    logger.info(
        "Queued %d email notification(s) for %s (request #%d)",
        len(recipients),
        event.kind.value,
        event.request_id,
    )
