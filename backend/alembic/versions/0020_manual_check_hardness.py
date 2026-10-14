"""add hardness to manual_quality_checks

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-11

Length and weight were already captured per manual QC check; hardness is added so
the operator's hardness measurement can be merged into the run/order summary and
pushed to the Odoo Quality Control tab together with length and weight.
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE manual_quality_checks
    ADD COLUMN IF NOT EXISTS hardness NUMERIC NULL;
"""

_DOWN = """
ALTER TABLE manual_quality_checks
    DROP COLUMN IF EXISTS hardness;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)