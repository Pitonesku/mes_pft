"""add triacetin target/tolerance + dry-sample flag

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-22

* quality_settings.triacetin_target / triacetin_tolerance
    factory defaults for LOCALLY-created MOs only (Odoo-pushed MOs get the
    effective target/tolerance from the Odoo product + MO quality-tab override).
* purchase_orders.triacetin / triacetin_tolerance
    per-item (order) triacetin target (%) and +/- tolerance (percentage points).
* quality_samples.is_triacetin
    marks a "dry" batch (rods measured without triacetin). Dry batches are
    excluded from every normal statistic and paired with a regular batch to
    compute the triacetin % in the quality report.
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE quality_settings
    ADD COLUMN IF NOT EXISTS triacetin_target NUMERIC NOT NULL DEFAULT 8.0,
    ADD COLUMN IF NOT EXISTS triacetin_tolerance NUMERIC NOT NULL DEFAULT 0.5;

ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS triacetin NUMERIC NULL,
    ADD COLUMN IF NOT EXISTS triacetin_tolerance NUMERIC NULL;

ALTER TABLE quality_samples
    ADD COLUMN IF NOT EXISTS is_triacetin BOOLEAN NOT NULL DEFAULT FALSE;
"""

_DOWN = """
ALTER TABLE quality_samples DROP COLUMN IF EXISTS is_triacetin;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS triacetin_tolerance;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS triacetin;
ALTER TABLE quality_settings DROP COLUMN IF EXISTS triacetin_tolerance;
ALTER TABLE quality_settings DROP COLUMN IF EXISTS triacetin_target;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
