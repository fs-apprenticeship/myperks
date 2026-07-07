# backend/tests/test_admin_employee_write.py
"""
Tests for:
  POST  /admin/employees        — pre-create employee row
  PATCH /admin/employees/{id}   — update department / role

Test matrix:
  - hr_admin -> 201 / 200 success + correct shape
  - duplicate email -> 409
  - unknown id -> 404
  - invalid department / role -> 422 (Pydantic validation)
  - employee role -> 403
  - no auth header -> 401
  - no fields in PATCH body -> no-op, still 200
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.auth import get_current_user
from db.session import get_session
from main import app

client = TestClient(app)

MOCK_CLERK_USER_ID = "clerk_admin_001"

# ── Mock factories ────────────────────────────────────────────────────────────


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


def make_employee(
    emp_id: int = 10,
    name: str = "Alice Smith",
    email: str = "alice@example.com",
    department: str = "engineering",
    role: str = "employee",
    clerk_user_id: str | None = None,
) -> MagicMock:
    emp = MagicMock()
    emp.id = emp_id
    emp.name = name
    emp.email = email
    emp.department = department
    emp.role = role
    emp.clerk_user_id = clerk_user_id
    emp.joined_date = "2023-03-15"
    emp.benefits_year_reset = "2025-01-01"
    return emp


# ── Helpers ───────────────────────────────────────────────────────────────────


def override_auth() -> str:
    return MOCK_CLERK_USER_ID


def make_db_override(
    mock_session: AsyncMock,
) -> Callable[[], AsyncGenerator[AsyncMock, None]]:
    async def override_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    return override_db


def auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer fake.jwt.token"}


def make_session(scalar_return: MagicMock | None) -> AsyncMock:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=scalar_return)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def make_scalar_one_result(value: MagicMock | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


VALID_PRE_CREATE_BODY = {
    "name": "Alice Smith",
    "email": "alice@example.com",
    "department": "engineering",
    "joined_date": "2023-03-15",
    "benefits_year_reset": "2025-01-01",
}


# ── POST /admin/employees ─────────────────────────────────────────────────────


class TestPreCreateEmployee:
    def test_hr_admin_creates_employee_201(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())
        # execute() for duplicate-email check returns None (no existing row)
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(None))
        # refresh() populates emp fields after commit
        mock_session.refresh = AsyncMock(side_effect=lambda e: None)

        # Simulate the created employee being returned after refresh
        emp_mock = make_employee()

        async def fake_refresh(obj: MagicMock) -> None:
            obj.id = emp_mock.id
            obj.name = emp_mock.name
            obj.email = emp_mock.email
            obj.department = emp_mock.department
            obj.role = emp_mock.role
            obj.joined_date = emp_mock.joined_date
            obj.benefits_year_reset = emp_mock.benefits_year_reset
            obj.clerk_user_id = None

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            with patch(
                "api.routers.admin.seed_employee_vacation_balances",
                new=AsyncMock(return_value=3),
            ):
                response = client.post(
                    "/admin/employees",
                    json=VALID_PRE_CREATE_BODY,
                    headers=auth_header(),
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 201
        data = response.json()
        for field in (
            "id",
            "name",
            "email",
            "department",
            "role",
            "joined_date",
            "benefits_year_reset",
            "linked",
        ):
            assert field in data, f"missing field: {field}"

    def test_linked_is_false_on_pre_create(self) -> None:
        emp_mock = make_employee()

        async def fake_refresh(obj: MagicMock) -> None:
            obj.id = emp_mock.id
            obj.name = emp_mock.name
            obj.email = emp_mock.email
            obj.department = emp_mock.department
            obj.role = emp_mock.role
            obj.joined_date = emp_mock.joined_date
            obj.benefits_year_reset = emp_mock.benefits_year_reset
            obj.clerk_user_id = None

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(None))
        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            with patch(
                "api.routers.admin.seed_employee_vacation_balances",
                new=AsyncMock(return_value=3),
            ):
                response = client.post(
                    "/admin/employees",
                    json=VALID_PRE_CREATE_BODY,
                    headers=auth_header(),
                )
        finally:
            app.dependency_overrides.clear()

        assert response.json()["linked"] is False

    def test_duplicate_email_returns_409(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())
        # execute() for duplicate-email check returns an existing employee
        mock_session.execute = AsyncMock(
            return_value=make_scalar_one_result(make_employee())
        )

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post(
                "/admin/employees",
                json=VALID_PRE_CREATE_BODY,
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409
        assert "email" in response.json()["detail"].lower()

    def test_invalid_department_returns_422(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post(
                "/admin/employees",
                json={**VALID_PRE_CREATE_BODY, "department": "invalid_dept"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_no_approved_policy_returns_422(self) -> None:
        # First db.scalar() call is require_admin's lookup, second is the
        # approved-policy check — must return admin then None, in that order.
        mock_session = make_session(scalar_return=None)
        mock_session.scalar = AsyncMock(side_effect=[make_admin_employee(), None])
        # execute() for duplicate-email check returns None (no existing row)
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(None))

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post(
                "/admin/employees",
                json=VALID_PRE_CREATE_BODY,
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "approved" in detail.lower()
        assert "engineering" in detail.lower()
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()

    def test_department_all_rejected_422(self) -> None:
        # "all" is a valid DB enum value (T39, document-only) but must never be
        # accepted for an employee. Guards against widening DEPARTMENT_VALUES.
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post(
                "/admin/employees",
                json={**VALID_PRE_CREATE_BODY, "department": "all"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_employee_role_returns_403(self) -> None:
        mock_session = make_session(scalar_return=make_non_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post(
                "/admin/employees",
                json=VALID_PRE_CREATE_BODY,
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_no_auth_header_returns_401(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.post("/admin/employees", json=VALID_PRE_CREATE_BODY)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401


# ── PATCH /admin/employees/{id} ───────────────────────────────────────────────


class TestPatchEmployee:
    def test_hr_admin_updates_department_200(self) -> None:
        emp = make_employee(department="engineering")

        async def fake_refresh(obj: MagicMock) -> None:
            obj.department = "sales"

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(emp))
        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"department": "sales"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        for field in (
            "id",
            "name",
            "email",
            "department",
            "role",
            "joined_date",
            "benefits_year_reset",
            "linked",
        ):
            assert field in data, f"missing field: {field}"

    def test_hr_admin_updates_role_200(self) -> None:
        emp = make_employee(role="employee")

        async def fake_refresh(obj: MagicMock) -> None:
            obj.role = "hr_admin"

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(emp))
        mock_session.refresh = AsyncMock(side_effect=fake_refresh)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"role": "hr_admin"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200

    def test_empty_body_is_noop_200(self) -> None:
        emp = make_employee()

        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(emp))
        mock_session.refresh = AsyncMock(side_effect=lambda e: None)

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200

    def test_invalid_department_returns_422(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"department": "invalid_dept"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_department_all_rejected_422(self) -> None:
        # "all" is document-only (T39); an employee can't be patched to it.
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"department": "all"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_invalid_role_returns_422(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"role": "superuser"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_unknown_id_returns_404(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())
        mock_session.execute = AsyncMock(return_value=make_scalar_one_result(None))

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/999999",
                json={"department": "sales"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_employee_role_returns_403(self) -> None:
        mock_session = make_session(scalar_return=make_non_admin_employee())

        app.dependency_overrides[get_current_user] = override_auth
        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch(
                "/admin/employees/10",
                json={"department": "sales"},
                headers=auth_header(),
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 403

    def test_no_auth_header_returns_401(self) -> None:
        mock_session = make_session(scalar_return=make_admin_employee())

        app.dependency_overrides[get_session] = make_db_override(mock_session)
        try:
            response = client.patch("/admin/employees/10", json={"department": "sales"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
