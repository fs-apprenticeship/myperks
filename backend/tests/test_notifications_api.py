import datetime
from collections.abc import AsyncIterator, Callable
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from api.auth import get_current_user
from db.session import get_session
from main import app

client = TestClient(app)


def override_auth() -> str:
    return "clerk_user_123"


def auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def make_employee(emp_id: int = 5) -> MagicMock:
    emp = MagicMock()
    emp.id = emp_id
    emp.clerk_user_id = "clerk_user_123"
    return emp


def make_notification(
    notif_id: int, recipient_id: int = 5, read: bool = False
) -> MagicMock:
    n = MagicMock()
    n.id = notif_id
    n.recipient_id = recipient_id
    n.type = "request_status_changed"
    n.message = f"Notification {notif_id}"
    n.payload = None
    n.read_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) if read else None
    n.related_request_id = 10
    n.created_at = datetime.datetime(2026, 1, notif_id, tzinfo=datetime.UTC)
    return n


def make_db_override(
    session: AsyncMock,
) -> Callable[[], AsyncIterator[AsyncMock]]:
    async def _override() -> AsyncIterator[AsyncMock]:
        yield session

    return _override


def make_scalars_all_result(rows: list[MagicMock]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def make_scalar_one_result(value: MagicMock | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def make_first_result(value: MagicMock | None) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


def make_one_result(value: tuple[int, int]) -> MagicMock:
    result = MagicMock()
    result.one = MagicMock(return_value=value)
    return result


# ── GET /me/notifications ─────────────────────────────────────────────────────


def test_list_returns_newest_first_with_unread_count() -> None:
    employee = make_employee()
    notes = [make_notification(3), make_notification(2), make_notification(1)]

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            make_first_result(employee),  # _get_employee
            make_one_result((3, 2)),  # total, unread_count
            make_scalars_all_result(notes),  # the page query
        ]
    )

    app.dependency_overrides[get_current_user] = override_auth
    app.dependency_overrides[get_session] = make_db_override(session)
    try:
        response = client.get("/me/notifications", headers=auth_header())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data["items"]] == [3, 2, 1]
    assert data["total"] == 3
    assert data["meta"]["unread_count"] == 2


# ── PATCH /me/notifications/{id}/read ─────────────────────────────────────────


def test_mark_read_sets_read_at() -> None:
    employee = make_employee()
    notification = make_notification(1, read=False)

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            make_first_result(employee),  # _get_employee
            make_scalar_one_result(notification),  # scoped lookup
        ]
    )

    app.dependency_overrides[get_current_user] = override_auth
    app.dependency_overrides[get_session] = make_db_override(session)
    try:
        response = client.patch("/me/notifications/1/read", headers=auth_header())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == 1
    session.commit.assert_awaited_once()
    assert notification.read_at is not None


def test_mark_read_other_users_notification_returns_404() -> None:
    employee = make_employee(emp_id=5)

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            make_first_result(employee),  # _get_employee
            make_scalar_one_result(None),  # scoped lookup finds nothing
        ]
    )

    app.dependency_overrides[get_current_user] = override_auth
    app.dependency_overrides[get_session] = make_db_override(session)
    try:
        response = client.patch("/me/notifications/999/read", headers=auth_header())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    session.commit.assert_not_called()


# ── PATCH /me/notifications/read-all ──────────────────────────────────────────


def test_mark_all_read_updates_unread() -> None:
    employee = make_employee()

    update_result = MagicMock()
    update_result.rowcount = 4

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            make_first_result(employee),  # _get_employee
            update_result,  # the bulk UPDATE
        ]
    )

    app.dependency_overrides[get_current_user] = override_auth
    app.dependency_overrides[get_session] = make_db_override(session)
    try:
        response = client.patch("/me/notifications/read-all", headers=auth_header())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["updated"] == 4
    session.commit.assert_awaited_once()
