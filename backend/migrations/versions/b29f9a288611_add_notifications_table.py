"""add notifications table

Revision ID: b29f9a288611
Revises: a7b8c9d0e1f2
Create Date: 2026-07-27 10:56:23.965459

In-app notifications: one row per recipient per request event.
Read state is the nullable read_at.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b29f9a288611"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'notification_type'
            ) THEN
                CREATE TYPE notification_type AS ENUM
                    ('request_submitted', 'request_status_changed');
            END IF;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id                  SERIAL PRIMARY KEY,
            recipient_id        INTEGER NOT NULL
                REFERENCES employees(id) ON DELETE CASCADE,
            related_request_id  INTEGER NOT NULL
                REFERENCES request_histories(id) ON DELETE CASCADE,
            type                notification_type NOT NULL,
            message             TEXT NOT NULL,
            payload             TEXT,
            read_at             TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_notifications_recipient_created
        ON notifications (recipient_id, created_at)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
    op.execute("DROP TYPE notification_type")
