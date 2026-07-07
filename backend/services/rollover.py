"""
myPerks — Vacation balance year rollover (T46)
backend/services/rollover.py

At each year boundary every existing employee needs a fresh set of
VacationBalance rows for the new year. We do this with a scheduled job (rather
than reacting to some per-row event) because it is a once-per-year, all-rows
operation: there's no natural "new year started" trigger on any one row.

The job delegates the actual logic to
``services.vacation.seed_employee_vacation_balances`` — the single source of
truth for proration and capped carryover — calling it once per employee. That
function skips leave types that already have a row for the year, so re-running
the job for a year that's already seeded is a no-op.
"""

from __future__ import annotations

import datetime
import logging
from typing import cast

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from db.models import Employee
from db.session import AsyncSessionLocal
from services.vacation import seed_employee_vacation_balances

logger = logging.getLogger(__name__)

_ROLLOVER_JOB_ID = "vacation_year_rollover"


async def run_year_rollover(year: int | None = None) -> int:
    """
    Seed ``year``'s vacation balances for every employee, prorating mid-year
    hires and carrying over capped unused days from the prior year. Returns
    the number of employees processed. Idempotent.
    """
    if year is None:
        year = datetime.date.today().year

    async with AsyncSessionLocal() as session:
        employees = (await session.scalars(select(Employee))).all()
        for employee in employees:
            await seed_employee_vacation_balances(
                session,
                cast(int, employee.id),
                employee.department,
                year,
                employee.joined_date,
            )
        await session.commit()

    logger.info(
        "Vacation year rollover for %d complete: processed %d employees",
        year,
        len(employees),
    )
    return len(employees)


def start_rollover_scheduler() -> AsyncIOScheduler:
    """
    Start an AsyncIOScheduler that runs the rollover a few minutes past midnight
    on Jan 1, so the new year's balances exist before anyone opens the app.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_year_rollover,
        CronTrigger(month=1, day=1, hour=0, minute=5),
        id=_ROLLOVER_JOB_ID,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Vacation year-rollover scheduler started (Jan 1 00:05)")
    return scheduler
