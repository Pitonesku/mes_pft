"""add station length + custom fields/metrics

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-14

* quality_measurements.length    - station-measured rod length (mm)
* quality_samples.custom_metrics - JSONB aggregates for configured custom fields
* station_profiles.custom_fields - JSONB list of {label, unit, index}
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE quality_measurements ADD COLUMN IF NOT EXISTS length NUMERIC NULL;
ALTER TABLE quality_samples ADD COLUMN IF NOT EXISTS custom_metrics JSONB NULL;
ALTER TABLE station_profiles ADD COLUMN IF NOT EXISTS custom_fields JSONB NULL;
"""

_DOWN = """
ALTER TABLE station_profiles DROP COLUMN IF EXISTS custom_fields;
ALTER TABLE quality_samples DROP COLUMN IF EXISTS custom_metrics;
ALTER TABLE quality_measurements DROP COLUMN IF EXISTS length;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
