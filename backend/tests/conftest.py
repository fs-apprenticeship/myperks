"""Shared fixtures for DB-backed tests.

Mock-session unit tests never touch these. Any test that requests ``db_session``
or ``api_client`` runs only when RUN_DB_TESTS=1 and a migrated Postgres is
reachable, and skips otherwise, so a plain ``pytest`` with no database still
passes.

The schema is not created here. CI runs ``alembic upgrade head`` against
myperks_test before pytest and these fixtures reuse that. Locally:

    createdb -U postgres -h localhost myperks_test
    psql "postgresql://postgres:postgres@localhost:5432/myperks_test" \
        -c "CREATE EXTENSION IF NOT EXISTS vector;"
    DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/myperks_test" \
        alembic upgrade head
    RUN_DB_TESTS=1 OPENAI_API_KEY=sk-dummy pytest

The gate is RUN_DB_TESTS rather than the RUN_DB_INTEGRATION flag test_ingest.py
uses: that fixture drops every table on teardown and calls the OpenAI API, and
neither should happen on a CI run.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Protocol

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from api.auth import get_current_user
from db.models import Employee, Notification, RequestHistory
from db.session import get_session
from main import app

CALLER_CLERK_ID = "clerk_caller"
OTHER_CLERK_ID = "clerk_other"

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/myperks_test"
)


def _database_url() -> str:
    return (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or DEFAULT_TEST_DATABASE_URL
    )


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Engine against the migrated test DB, or skip if DB tests are off.

    Function-scoped on purpose. A session-scoped async engine binds to an event
    loop that pytest-asyncio tears down after each test, which surfaces later as
    "attached to a different loop".
    """
    if not os.getenv("RUN_DB_TESTS"):
        pytest.skip("set RUN_DB_TESTS=1 with DATABASE_URL on a migrated test DB")

    engine = create_async_engine(_database_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction that is always rolled back.

    ``join_transaction_mode="create_savepoint"`` makes the router's own
    ``db.commit()`` release a savepoint instead of committing the outer
    transaction, so writes are visible to the test and gone afterwards. No
    truncation, and nothing leaks between tests.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the app with the test session and caller injected.

    httpx + ASGITransport rather than TestClient: TestClient drives the app on
    its own event loop, which a real asyncpg connection created here cannot be
    used from.
    """

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _auth_override() -> str:
        return CALLER_CLERK_ID

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _auth_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)


async def _seed_employee(
    session: AsyncSession, clerk_user_id: str, email: str
) -> Employee:
    """One employee plus one request row for notifications to hang off."""
    employee = Employee(
        clerk_user_id=clerk_user_id,
        name=email.split("@")[0],
        email=email,
        department="engineering",
        joined_date=date(2025, 1, 1),
        benefits_year_reset=date(2026, 1, 1),
    )
    session.add(employee)
    await session.flush()

    session.add(RequestHistory(employee_id=employee.id, type="vacation", body="{}"))
    await session.flush()
    return employee


@pytest.fixture
async def caller(db_session: AsyncSession) -> Employee:
    """The authenticated employee that api_client acts as."""
    return await _seed_employee(db_session, CALLER_CLERK_ID, "caller@example.com")


@pytest.fixture
async def other_user(db_session: AsyncSession) -> Employee:
    """A second employee, used to prove queries are scoped to the caller."""
    return await _seed_employee(db_session, OTHER_CLERK_ID, "other@example.com")


class AddNotification(Protocol):
    async def __call__(
        self, recipient: Employee, *, day: int, read: bool = False
    ) -> Notification: ...


@pytest.fixture
def add_notification(db_session: AsyncSession) -> AddNotification:
    """Insert one notification for a recipient, dated 2026-01-<day>."""

    async def _add(
        recipient: Employee, *, day: int, read: bool = False
    ) -> Notification:
        request = await db_session.scalar(
            select(RequestHistory).where(RequestHistory.employee_id == recipient.id)
        )
        assert request is not None
        notification = Notification(
            recipient_id=recipient.id,
            related_request_id=request.id,
            type="request_status_changed",
            message=f"notification day {day}",
            created_at=datetime(2026, 1, day, tzinfo=UTC),
            read_at=datetime(2026, 1, 1, tzinfo=UTC) if read else None,
        )
        db_session.add(notification)
        await db_session.flush()
        return notification

    return _add
