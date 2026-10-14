"""add shift_name + scheduled_end_at for shift lifecycle (auto-close)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10

Enables the time-based auto-close sweep (IN_PROGRESS -> AUTO_CLOSED once the
scheduled end has passed by >30 min without a final report) and keeps the shift
template label for the pending-reports UI.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE shift_sessions ADD COLUMN IF NOT EXISTS shift_name VARCHAR(50) NULL;
ALTER TABLE shift_sessions ADD COLUMN IF NOT EXISTS scheduled_end_at TIMESTAMPTZ NULL;
"""

_DOWN = """
ALTER TABLE shift_sessions DROP COLUMN IF EXISTS scheduled_end_at;
ALTER TABLE shift_sessions DROP COLUMN IF EXISTS shift_name;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
