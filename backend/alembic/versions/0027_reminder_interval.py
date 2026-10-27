"""add per-machine manual-test reminder interval

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-26

* machines.reminder_interval_minutes (INTEGER)
    minutes between manual QC tests before the operator app raises an in-app
    "dead man's switch" reminder. NULL or 0 = disabled.
"""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE machines
    ADD COLUMN IF NOT EXISTS reminder_interval_minutes INTEGER NULL;
"""

_DOWN = """
ALTER TABLE machines DROP COLUMN IF EXISTS reminder_interval_minutes;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
