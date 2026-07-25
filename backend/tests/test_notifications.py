from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks

from services import notifications
from services.email import send_email
from services.notifications import (
    Recipient,
    dispatch,
    request_status_changed,
    request_submitted,
    resolve_recipients,
)


def _employee(emp_id: int, email: str, name: str) -> MagicMock:
    emp = MagicMock()
    emp.id = emp_id
    emp.email = email
    emp.name = name
    return emp


def _scalars_returning(rows: list[MagicMock]) -> AsyncMock:
    """Mock db.scalars(...) -> result whose .all() yields ``rows``."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return AsyncMock(return_value=result)


def _execute_returning(objs: list[MagicMock | None]) -> AsyncMock:
    """Mock db.execute(...): each call yields the next .scalar_one_or_none()."""
    results = []
    for obj in objs:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=obj)
        results.append(result)
    return AsyncMock(side_effect=results)


# ── resolve_recipients ────────────────────────────────────────────────────────


async def test_resolve_recipients_submitted_returns_all_hr_admins() -> None:
    db = MagicMock()
    db.scalars = _scalars_returning(
        [_employee(1, "a@corp.com", "Ana"), _employee(2, "b@corp.com", "Ben")]
    )
    event = request_submitted(
        request_id=10, request_type="vacation", submitter_name="Cy"
    )

    recipients = await resolve_recipients(db, event)

    assert recipients == [
        Recipient(id=1, email="a@corp.com", name="Ana"),
        Recipient(id=2, email="b@corp.com", name="Ben"),
    ]


async def test_resolve_recipients_status_changed_returns_the_submitter() -> None:
    request = MagicMock()
    request.employee_id = 7
    submitter = _employee(7, "sub@corp.com", "Sam")
    db = MagicMock()
    db.execute = _execute_returning([request, submitter])
    event = request_status_changed(
        request_id=10, request_type="pto", new_status="approved"
    )

    recipients = await resolve_recipients(db, event)

    assert recipients == [Recipient(id=7, email="sub@corp.com", name="Sam")]


async def test_resolve_recipients_status_changed_missing_request_is_empty() -> None:
    db = MagicMock()
    db.execute = _execute_returning([None])
    event = request_status_changed(
        request_id=999, request_type="pto", new_status="approved"
    )

    assert await resolve_recipients(db, event) == []


# ── dispatch ──────────────────────────────────────────────────────────────────


async def test_dispatch_enqueues_one_email_task_per_recipient() -> None:
    db = MagicMock()
    recipients = [
        Recipient(id=1, email="a@corp.com", name="Ana"),
        Recipient(id=2, email="b@corp.com", name="Ben"),
    ]
    background = BackgroundTasks()
    event = request_submitted(
        request_id=10, request_type="vacation", submitter_name="Cy"
    )

    with (
        patch.object(
            notifications, "resolve_recipients", AsyncMock(return_value=recipients)
        ),
        patch.object(
            notifications, "settings", MagicMock(notifications_email_enabled=True)
        ),
    ):
        await dispatch(background, db, event)

    assert len(background.tasks) == 2
    assert all(cast(object, task.func) is send_email for task in background.tasks)
    assert [task.kwargs["to"] for task in background.tasks] == [
        "a@corp.com",
        "b@corp.com",
    ]
    first = background.tasks[0].kwargs
    assert first["subject"] == "New vacation request from Cy"
    assert "#10" in cast(str, first["body"])


async def test_dispatch_is_a_noop_when_email_disabled() -> None:
    db = MagicMock()
    background = BackgroundTasks()
    event = request_submitted(
        request_id=10, request_type="vacation", submitter_name="Cy"
    )

    with (
        patch.object(
            notifications,
            "resolve_recipients",
            AsyncMock(return_value=[Recipient(id=1, email="a@corp.com", name="Ana")]),
        ),
        patch.object(
            notifications, "settings", MagicMock(notifications_email_enabled=False)
        ),
    ):
        await dispatch(background, db, event)

    assert background.tasks == []


# ── _render ───────────────────────────────────────────────────────────────────


def test_render_status_changed_includes_rejection_reason() -> None:
    event = request_status_changed(
        request_id=5,
        request_type="vacation",
        new_status="rejected",
        rejection_reason="Blackout period",
    )

    subject, body = notifications._render(event)

    assert subject == "Your vacation request was rejected"
    assert "Blackout period" in body


def test_render_submitted_names_the_submitter() -> None:
    event = request_submitted(request_id=5, request_type="sick", submitter_name="Dana")

    subject, body = notifications._render(event)

    assert "Dana" in subject
    assert "sick" in subject
