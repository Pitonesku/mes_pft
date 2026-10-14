"""add end_counter to production_runs (run-split segment tracking)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-10

When an operator switches MO mid-shift, the previous run is closed with a final
machine counter so the produced-quantity split is preserved for the report.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_UP = "ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS end_counter NUMERIC NULL;"
_DOWN = "ALTER TABLE production_runs DROP COLUMN IF EXISTS end_counter;"


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
