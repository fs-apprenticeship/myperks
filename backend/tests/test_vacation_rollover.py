"""
backend/tests/test_vacation_rollover.py

Tests for:
- services.vacation.seed_employee_vacation_balances — the proration/carryover
  logic (T46). Session DB calls are mocked; `_get_approved_policy` and
  `_prior_year_remaining` are patched directly since they're the only points
  where the function talks to the DB for policy/history lookups.
- services.rollover — the year-rollover job that calls it once per employee.
"""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from services import rollover, vacation
from services.vacation import _months_remaining, seed_employee_vacation_balances

# ── _months_remaining: pure proration math ────────────────────────────────────


def test_months_remaining_is_twelve_for_a_prior_year_hire() -> None:
    assert _months_remaining(datetime.date(2024, 6, 1), 2026) == 12


def test_months_remaining_counts_hire_month_as_worked() -> None:
    assert _months_remaining(datetime.date(2026, 1, 10), 2026) == 12
    assert _months_remaining(datetime.date(2026, 11, 10), 2026) == 2


def test_months_remaining_is_twelve_when_joined_date_unknown() -> None:
    assert _months_remaining(None, 2026) == 12


# ── seed_employee_vacation_balances ───────────────────────────────────────────


def _make_session(existing_types: list[str] | None = None) -> MagicMock:
    session = MagicMock()
    existing_types = existing_types or []
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=existing_types)
    session.scalars = AsyncMock(return_value=scalars_result)
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    return session


async def test_january_hire_gets_full_allotment() -> None:
    session = _make_session()
    with (
        patch.object(vacation, "_get_approved_policy", AsyncMock(return_value={})),
        patch.object(vacation, "_prior_year_remaining", AsyncMock(return_value=None)),
    ):
        created = await seed_employee_vacation_balances(
            session, 1, "operations", 2026, datetime.date(2026, 1, 10)
        )

    assert created == 3
    totals = {b.leave_type: b.total_days for b in session.add_all.call_args.args[0]}
    assert totals == {"vacation": 15.0, "sick": 10.0, "pto": 5.0}


async def test_november_hire_is_prorated_to_nearest_half_day() -> None:
    session = _make_session()
    with (
        patch.object(vacation, "_get_approved_policy", AsyncMock(return_value={})),
        patch.object(vacation, "_prior_year_remaining", AsyncMock(return_value=None)),
    ):
        await seed_employee_vacation_balances(
            session, 1, "operations", 2026, datetime.date(2026, 11, 10)
        )

    totals = {b.leave_type: b.total_days for b in session.add_all.call_args.args[0]}
    # 2 months remaining: 15*2/12=2.5, 10*2/12=1.67->1.5, 5*2/12=0.83->1.0
    assert totals == {"vacation": 2.5, "sick": 1.5, "pto": 1.0}


async def test_carryover_is_capped_at_default_five_days() -> None:
    session = _make_session()
    with (
        patch.object(vacation, "_get_approved_policy", AsyncMock(return_value={})),
        patch.object(
            vacation,
            "_prior_year_remaining",
            AsyncMock(side_effect=[12.0, 0.0, 0.0]),  # vacation, sick, pto
        ),
    ):
        await seed_employee_vacation_balances(
            session, 1, "operations", 2027, datetime.date(2025, 1, 10)
        )

    totals = {b.leave_type: b.total_days for b in session.add_all.call_args.args[0]}
    assert totals["vacation"] == 20.0  # 15 full + min(12, cap 5)


async def test_policy_overrides_days_and_grants_uncapped_carryover() -> None:
    session = _make_session()
    policy = {
        "vacation_days": 20,
        "carryover_cap_days": None,  # uncapped
        "proration_method": "none",
    }
    with (
        patch.object(vacation, "_get_approved_policy", AsyncMock(return_value=policy)),
        patch.object(
            vacation, "_prior_year_remaining", AsyncMock(side_effect=[18.0, 0.0, 0.0])
        ),
    ):
        await seed_employee_vacation_balances(
            session, 1, "engineering", 2027, datetime.date(2026, 11, 1)
        )

    totals = {b.leave_type: b.total_days for b in session.add_all.call_args.args[0]}
    # proration_method "none" -> full 20 despite the Nov join date.
    assert totals["vacation"] == 38.0  # 20 + 18 uncapped


async def test_skips_leave_types_that_already_have_a_row_for_the_year() -> None:
    session = _make_session(existing_types=["vacation", "sick", "pto"])

    with patch.object(vacation, "_get_approved_policy", AsyncMock(return_value={})):
        created = await seed_employee_vacation_balances(
            session, 1, "operations", 2026, datetime.date(2026, 1, 10)
        )

    assert created == 0
    session.add_all.assert_not_called()


# ── Rollover job ──────────────────────────────────────────────────────────────


async def test_run_year_rollover_seeds_every_employee() -> None:
    employees = [
        MagicMock(id=i, department="engineering", joined_date=None) for i in range(3)
    ]

    session = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=employees)
    session.scalars = AsyncMock(return_value=scalars_result)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[MagicMock]:
        yield session

    with (
        patch.object(rollover, "AsyncSessionLocal", fake_session),
        patch.object(
            rollover, "seed_employee_vacation_balances", AsyncMock(return_value=3)
        ) as seed_mock,
    ):
        processed = await rollover.run_year_rollover(2027)

    assert processed == 3
    assert seed_mock.await_count == 3
    session.commit.assert_awaited_once()


def test_start_rollover_scheduler_registers_annual_job() -> None:
    sched = rollover.start_rollover_scheduler()
    try:
        job = sched.get_job("vacation_year_rollover")
        assert job is not None
        assert job.func is rollover.run_year_rollover
    finally:
        sched.shutdown(wait=False)
