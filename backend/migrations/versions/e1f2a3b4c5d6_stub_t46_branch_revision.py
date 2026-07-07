"""stub — T46 revision applied to prod from an unmerged branch before main had it

This revision was deployed to the production database from the
t46-vacation-rollover-proration branch (which drops the
seed_employee_vacation_balances()/trigger pair added in d4f5a6b7c8e9 in favor
of a Python implementation), but that branch was never merged to main and its
migration file was never committed here. Without this stub, alembic on main
cannot locate the revision the database is stamped at and every deploy fails
with "Can't locate revision identified by 'e1f2a3b4c5d6'".

This is a no-op: it does not perform the DDL the original migration did. When
the real T46 work merges, its migration chain should re-parent onto this
revision (or replace it) rather than redefine "e1f2a3b4c5d6" again.

Revision ID: e1f2a3b4c5d6
Revises: d4f5a6b7c8e9
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d4f5a6b7c8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
