# backend/tests/test_admin.py
"""
Unit tests for PATCH /admin/requests/{id}, gated by require_admin.

Test matrix (T22):
  - hr_admin role            -> 200, request approved/rejected
  - employee role            -> 403
  - no matching Employee row -> 403
  - no Authorization header  -> 401
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.auth import get_current_user
from db.session import get_session
from main import app

client = TestClient(app)

# ── Mock data ─────────────────────────────────────────────────────────────────

MOCK_CLERK_USER_ID = "clerk_admin_001"


def make_admin_employee() -> MagicMock:
    admin = MagicMock()
    admin.id = 1
    admin.role = "hr_admin"
    return admin


def make_non_admin_employee() -> MagicMock:
    emp = MagicMock()
    emp.id = 2
    emp.role = "employee"
    return emp


def make_pending_request(
    request_id: int = 10, employee_id: int = 5, req_type: str = "vacation"
) -> MagicMock:
    req = MagicMock()
    req.id = request_id
    req.employee_id = employee_id
    req.type = req_type
    req.status = "pending"
    req.body = None
    return req


def make_requesting_employee(employee_id: int = 5) -> MagicMock:
    emp = MagicMock()
    emp.id = employee_id
    emp.name = "Jane Doe"
    emp.email = "jane@example.com"
    return emp


# ── Helpers ───────────────────────────────────────────────────────────────────


def override_auth() -> str:
    """Replacement for get_current_user — returns mock clerk_user_id."""
    return MOCK_CLERK_USER_ID


def make_db_override(
    mock_session: AsyncMock,
) -> Callable[[], AsyncGenerator[AsyncMock, None]]:
    """Returns an async generator that yields the mock session."""

    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    return override_db


def auth_header() -> dict[str, str]:
    """Returns a fake Authorization header."""
    return {"Authorization": "Bearer fake.jwt.token"}


def make_session(scalar_return: MagicMock | None) -> AsyncMock:
    """
    Mock session for require_admin's `await session.scalar(...)` lookup,
    plus empty commit/execute for the route handler.
    """
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=scalar_return)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


def make_scalar_one_result(value: MagicMock | None) -> MagicMock:
    """Mock execute() result where .scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def make_scalars_all_result(values: list[MagicMock]) -> MagicMock:
    """Mock execute() result where .scalars().all() returns values."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


# ── PATCH /admin/requests/{id} ────────────────────────────────────────────────


class TestApproveOrRejectRequest:
    def test_hr_admin_can_approve_request(self) -> None:
        """hr_admin role -> 200, request approved."""
        req = make_pending_request(req_type="vacation")
        requesting_emp = make_requesting_employee(employee_id=req.employee_id)

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(
            side_effect=[
                make_scalar_one_result(req),
                make_scalar_one_result(requesting_emp),
                make_scalars_all_result([]),
            ]
        )

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            with patch("api.routers.admin.dispatch", new_callable=AsyncMock):
                response = client.patch(
                    f"/admin/requests/{req.id}",
                    json={"status": "approved"},
                    headers=auth_header(),
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == req.id
        assert data["new_status"] == "approved"
        assert data["employee_email"] == requesting_emp.email
        mock_session.commit.assert_awaited_once()

    def test_employee_role_returns_403(self) -> None:
        """employee role -> 403, no business logic runs."""
        mock_session = make_session(scalar_return=make_non_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/requests/10",
                json={"status": "approved"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403
        assert "hr admin" in response.json()["detail"].lower()
        mock_session.execute.assert_not_called()

    def test_no_employee_record_returns_403(self) -> None:
        """Authenticated Clerk user with no Employee row -> 403."""
        mock_session = make_session(scalar_return=None)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/requests/10",
                json={"status": "approved"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_no_auth_header_returns_401(self) -> None:
        """No Authorization header -> 401 before any business logic runs."""
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/requests/10",
                json={"status": "approved"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        mock_session.execute.assert_not_called()


class TestApproveOrRejectNotifications:
    """T53 — status-changed notifications on approve/reject.

    dispatch() is patched out; these assert the trigger fires with the right
    event and that a failing/disabled notification never affects the response.
    """

    def test_approve_dispatches_status_changed_to_owner(self) -> None:
        req = make_pending_request(req_type="vacation")
        requesting_emp = make_requesting_employee(employee_id=req.employee_id)

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(
            side_effect=[
                make_scalar_one_result(req),
                make_scalar_one_result(requesting_emp),
                make_scalars_all_result([]),
            ]
        )

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        with patch(
            "api.routers.admin.dispatch", new_callable=AsyncMock
        ) as mock_dispatch:
            try:
                response = client.patch(
                    f"/admin/requests/{req.id}",
                    json={"status": "approved"},
                    headers=auth_header(),
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        mock_dispatch.assert_awaited_once()
        # dispatch(background_tasks, db, event) — event is the 3rd positional arg
        await_args = mock_dispatch.await_args
        assert await_args is not None
        event = await_args.args[2]
        assert event.request_id == req.id
        assert event.new_status == "approved"
        assert event.rejection_reason is None
        assert event.request_type == "vacation"

    def test_reject_dispatches_with_reason(self) -> None:
        req = make_pending_request(req_type="vacation")
        requesting_emp = make_requesting_employee(employee_id=req.employee_id)

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(
            side_effect=[
                make_scalar_one_result(req),
                make_scalar_one_result(requesting_emp),
                make_scalars_all_result([]),
            ]
        )

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        with patch(
            "api.routers.admin.dispatch", new_callable=AsyncMock
        ) as mock_dispatch:
            try:
                response = client.patch(
                    f"/admin/requests/{req.id}",
                    json={"status": "rejected", "rejection_reason": "Blackout period"},
                    headers=auth_header(),
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        mock_dispatch.assert_awaited_once()
        await_args = mock_dispatch.await_args
        assert await_args is not None
        event = await_args.args[2]
        assert event.request_id == req.id
        assert event.new_status == "rejected"
        assert event.rejection_reason == "Blackout period"
        assert event.request_type == "vacation"

    def test_notification_failure_does_not_break_response(self) -> None:
        req = make_pending_request(req_type="vacation")
        requesting_emp = make_requesting_employee(employee_id=req.employee_id)

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(
            side_effect=[
                make_scalar_one_result(req),
                make_scalar_one_result(requesting_emp),
                make_scalars_all_result([]),
            ]
        )

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        with patch(
            "api.routers.admin.dispatch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            try:
                response = client.patch(
                    f"/admin/requests/{req.id}",
                    json={"status": "approved"},
                    headers=auth_header(),
                )
            finally:
                app.dependency_overrides.clear()

        # Notification blew up, but the request still succeeded and committed.
        assert response.status_code == 200
        assert response.json()["new_status"] == "approved"
        mock_session.commit.assert_awaited_once()
