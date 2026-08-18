"""DB-backed tests for the notifications API.

These complement tests/test_notifications_api.py, which mocks the session and so
cannot catch a wrong ORDER BY, a wrong OFFSET, or a missing recipient filter.
Every assertion here runs against real query results. Skipped unless
RUN_DB_TESTS=1, see tests/conftest.py.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Employee
from tests.conftest import AddNotification

# ── GET /me/notifications ─────────────────────────────────────────────────────


async def test_list_returns_newest_first(
    api_client: AsyncClient,
    caller: Employee,
    add_notification: AddNotification,
) -> None:
    """Insertion order differs from created_at order, so a dropped ORDER BY fails."""
    await add_notification(caller, day=2)
    await add_notification(caller, day=5)
    await add_notification(caller, day=1)
    await add_notification(caller, day=4)

    response = await api_client.get("/me/notifications")

    assert response.status_code == 200
    messages = [item["message"] for item in response.json()["items"]]
    assert messages == [
        "notification day 5",
        "notification day 4",
        "notification day 2",
        "notification day 1",
    ]


async def test_list_pagination_slices(
    api_client: AsyncClient,
    caller: Employee,
    add_notification: AddNotification,
) -> None:
    for day in (1, 2, 3, 4, 5):
        await add_notification(caller, day=day)

    first = await api_client.get("/me/notifications?page=1&page_size=2")
    second = await api_client.get("/me/notifications?page=2&page_size=2")
    third = await api_client.get("/me/notifications?page=3&page_size=2")

    assert [item["message"] for item in first.json()["items"]] == [
        "notification day 5",
        "notification day 4",
    ]
    assert [item["message"] for item in second.json()["items"]] == [
        "notification day 3",
        "notification day 2",
    ]
    assert [item["message"] for item in third.json()["items"]] == ["notification day 1"]
    # total counts every row, not just the page.
    assert first.json()["total"] == 5


async def test_list_page_past_the_end_is_empty(
    api_client: AsyncClient,
    caller: Employee,
    add_notification: AddNotification,
) -> None:
    await add_notification(caller, day=1)

    response = await api_client.get("/me/notifications?page=9&page_size=20")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 1


async def test_list_is_scoped_to_caller(
    api_client: AsyncClient,
    caller: Employee,
    other_user: Employee,
    add_notification: AddNotification,
) -> None:
    await add_notification(caller, day=1)
    await add_notification(caller, day=2, read=True)
    await add_notification(other_user, day=3)
    await add_notification(other_user, day=4)

    data = (await api_client.get("/me/notifications")).json()

    assert [item["message"] for item in data["items"]] == [
        "notification day 2",
        "notification day 1",
    ]
    assert data["total"] == 2
    assert data["meta"]["unread_count"] == 1


# ── PATCH /me/notifications/{id}/read ─────────────────────────────────────────


async def test_mark_read_persists_read_at(
    api_client: AsyncClient,
    db_session: AsyncSession,
    caller: Employee,
    add_notification: AddNotification,
) -> None:
    notification = await add_notification(caller, day=1)

    response = await api_client.patch(f"/me/notifications/{notification.id}/read")

    assert response.status_code == 200
    assert response.json()["read_at"] is not None
    await db_session.refresh(notification)
    assert notification.read_at is not None


async def test_mark_read_other_users_notification_404s_and_leaves_it_unread(
    api_client: AsyncClient,
    db_session: AsyncSession,
    caller: Employee,
    other_user: Employee,
    add_notification: AddNotification,
) -> None:
    theirs = await add_notification(other_user, day=1)

    response = await api_client.patch(f"/me/notifications/{theirs.id}/read")

    assert response.status_code == 404
    await db_session.refresh(theirs)
    assert theirs.read_at is None


async def test_mark_read_unknown_id_404s(
    api_client: AsyncClient,
    caller: Employee,
) -> None:
    response = await api_client.patch("/me/notifications/999999/read")

    assert response.status_code == 404


# ── PATCH /me/notifications/read-all ──────────────────────────────────────────


async def test_read_all_marks_only_callers_unread(
    api_client: AsyncClient,
    db_session: AsyncSession,
    caller: Employee,
    other_user: Employee,
    add_notification: AddNotification,
) -> None:
    await add_notification(caller, day=1)
    await add_notification(caller, day=2)
    already_read = await add_notification(caller, day=3, read=True)
    theirs = await add_notification(other_user, day=4)

    response = await api_client.patch("/me/notifications/read-all")

    assert response.status_code == 200
    # Only the two unread rows, not the one already read.
    assert response.json()["updated"] == 2

    await db_session.refresh(theirs)
    assert theirs.read_at is None, "read-all touched another user's row"

    data = (await api_client.get("/me/notifications")).json()
    assert data["meta"]["unread_count"] == 0
    assert already_read.read_at is not None
