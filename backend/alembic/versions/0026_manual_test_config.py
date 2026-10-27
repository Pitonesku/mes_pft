"""add per-machine manual test config + manual triacetin fallback columns

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-26

* machines.manual_test_config (JSONB)
    per-machine visibility/required flags for each manual QC parameter
    (weight, length, hardness, glue_seam, cut_quality, visual_cleanness,
    triacetin). NULL = factory default (all visible, none required).

* manual_quality_checks.triacetin_* columns
    operator manual triacetin fallback: wet weight (mg), dry weight (mg),
    rods count and the server-computed percentage ((wet-dry)/dry*100).
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE machines
    ADD COLUMN IF NOT EXISTS manual_test_config JSONB NULL;

ALTER TABLE manual_quality_checks
    ADD COLUMN IF NOT EXISTS triacetin_wet_mg NUMERIC NULL,
    ADD COLUMN IF NOT EXISTS triacetin_dry_mg NUMERIC NULL,
    ADD COLUMN IF NOT EXISTS triacetin_rods INTEGER NULL,
    ADD COLUMN IF NOT EXISTS triacetin_pct NUMERIC NULL;
"""

_DOWN = """
ALTER TABLE manual_quality_checks
    DROP COLUMN IF EXISTS triacetin_pct,
    DROP COLUMN IF EXISTS triacetin_rods,
    DROP COLUMN IF EXISTS triacetin_dry_mg,
    DROP COLUMN IF EXISTS triacetin_wet_mg;

ALTER TABLE machines DROP COLUMN IF EXISTS manual_test_config;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
