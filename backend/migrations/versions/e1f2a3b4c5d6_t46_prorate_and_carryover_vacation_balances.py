"""t46 prorate mid-year hires and carry over unused vacation

Revision ID: e1f2a3b4c5d6
Revises: d4f5a6b7c8e9
Create Date: 2026-06-29 00:00:00.000000

Adds mid-year-hire proration and capped carryover to vacation-balance seeding
(T46): a new hire's first-year allotment is prorated by months remaining
(``policy_days * months_remaining / 12``, half-day rounded), and unused days
carry over from the prior year capped per the department policy's
``carryover_cap_days`` (default: vacation 5, sick/PTO none).

This logic lives in Python (``services.vacation.seed_employee_vacation_balances``)
rather than in the plpgsql function migration d4f5a6b7c8e9 introduced, so it's
unit-testable without a Postgres instance and doesn't need a parallel
SQL/Python implementation kept in sync. This migration drops that function and
its AFTER INSERT trigger; employee creation (admin.pre_create_employee) and
the year-boundary rollover job (services/rollover.py) both call the Python
function directly instead.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d4f5a6b7c8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED_FN_V1 = """
CREATE OR REPLACE FUNCTION seed_employee_vacation_balances(
    p_employee_id INTEGER,
    p_department department,
    p_year INTEGER
) RETURNS VOID AS $$
DECLARE
    policy jsonb;
BEGIN
    SELECT de.approved_data::jsonb INTO policy
    FROM document_extractions de
    JOIN documents d ON d.id = de.document_id
    WHERE d.department = p_department
      AND de.status = 'approved'
    ORDER BY de.reviewed_at DESC
    LIMIT 1;

    INSERT INTO vacation_balances
        (employee_id, leave_type, total_days, used_days, year)
    VALUES
        (p_employee_id, 'vacation',
         COALESCE((policy->>'vacation_days')::numeric, 15), 0, p_year),
        (p_employee_id, 'sick',
         COALESCE((policy->>'sick_days')::numeric, 10), 0, p_year),
        (p_employee_id, 'pto',
         COALESCE((policy->>'pto_days')::numeric, 5), 0, p_year)
    ON CONFLICT (employee_id, year, leave_type) DO NOTHING;
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER_FN_V1 = """
CREATE OR REPLACE FUNCTION trg_seed_vacation_balances_on_employee_insert()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM seed_employee_vacation_balances(
        NEW.id, NEW.department, EXTRACT(YEAR FROM now())::int
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS seed_vacation_balances_on_employee_insert ON employees"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS trg_seed_vacation_balances_on_employee_insert()"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "seed_employee_vacation_balances(INTEGER, department, INTEGER)"
    )


def downgrade() -> None:
    op.execute(_SEED_FN_V1)
    op.execute(_TRIGGER_FN_V1)
    op.execute(
        "DROP TRIGGER IF EXISTS seed_vacation_balances_on_employee_insert ON employees"
    )
    op.execute(
        """
        CREATE TRIGGER seed_vacation_balances_on_employee_insert
        AFTER INSERT ON employees
        FOR EACH ROW
        EXECUTE FUNCTION trg_seed_vacation_balances_on_employee_insert()
        """
    )
