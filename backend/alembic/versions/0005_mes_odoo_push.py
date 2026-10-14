"""mes odoo push integration

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06

Adds the MES side of the Odoo push (webhook) integration and the
human-in-the-loop report verification workflow:

  * production_run_components — filtered BOM (direct filter-rod materials)
    pushed from Odoo when a Manufacturing Order is confirmed.
  * production_reports.verification_status / verified_by / verified_at —
    operator data is "pending" until a supervisor approves it.

All new columns are additive and NULL/default-safe for existing rows; no data
is deleted or overwritten (invariant #2).
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS production_run_components (
    id BIGSERIAL PRIMARY KEY,
    po_id INTEGER NULL REFERENCES purchase_orders(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    seq INTEGER NOT NULL DEFAULT 0,
    category VARCHAR(50) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    product_qty NUMERIC(14, 4) NOT NULL DEFAULT 0,
    product_uom VARCHAR(20) NULL,
    material_id INTEGER NULL REFERENCES material_dictionary(id),
    batch_no VARCHAR(100) NULL,
    odoo_bom_line_id INTEGER NULL,
    odoo_move_id INTEGER NULL
);

CREATE INDEX IF NOT EXISTS ix_production_run_components_po_id
    ON production_run_components (po_id);
CREATE INDEX IF NOT EXISTS ix_production_run_components_run_id
    ON production_run_components (run_id);

ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) NOT NULL DEFAULT 'pending';
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS verified_by VARCHAR(50) NULL;
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_production_reports_verification_status
    ON production_reports (verification_status);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_production_reports_verification_status;
ALTER TABLE production_reports DROP COLUMN IF EXISTS verified_at;
ALTER TABLE production_reports DROP COLUMN IF EXISTS verified_by;
ALTER TABLE production_reports DROP COLUMN IF EXISTS verification_status;

DROP INDEX IF EXISTS ix_production_run_components_run_id;
DROP INDEX IF EXISTS ix_production_run_components_po_id;
DROP TABLE IF EXISTS production_run_components;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
