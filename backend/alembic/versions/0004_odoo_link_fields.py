"""odoo link fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05

Adds nullable, non-destructive Odoo integration columns:
  * purchase_orders.odoo_id                  -> sale.order (customer PO)
  * material_dictionary.odoo_product_id      -> product.product
  * material_dictionary.odoo_uom_id          -> uom.uom
  * material_logs.odoo_lot_id                -> stock.lot (batch/lot reference)
  * production_runs.odoo_backorder_id        -> mrp.production backorder
  * production_runs.odoo_done_qty            -> last synced completion qty
  * production_runs.odoo_sync_status         -> pending | synced | error

All new columns are NULL for existing rows; linking is additive only. No data is
deleted or overwritten.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_id INTEGER NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_purchase_orders_odoo_id
    ON purchase_orders (odoo_id) WHERE odoo_id IS NOT NULL;

ALTER TABLE material_dictionary ADD COLUMN IF NOT EXISTS odoo_product_id INTEGER NULL;
ALTER TABLE material_dictionary ADD COLUMN IF NOT EXISTS odoo_uom_id INTEGER NULL;

ALTER TABLE material_logs ADD COLUMN IF NOT EXISTS odoo_lot_id INTEGER NULL;

ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS odoo_backorder_id INTEGER NULL;
ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS odoo_done_qty NUMERIC NULL;
ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS odoo_sync_status VARCHAR(20) NOT NULL DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS ix_odoo_outbox_status_attempt
    ON odoo_outbox (status, next_attempt_at);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_odoo_outbox_status_attempt;
ALTER TABLE production_runs DROP COLUMN IF EXISTS odoo_sync_status;
ALTER TABLE production_runs DROP COLUMN IF EXISTS odoo_done_qty;
ALTER TABLE production_runs DROP COLUMN IF EXISTS odoo_backorder_id;
ALTER TABLE material_logs DROP COLUMN IF EXISTS odoo_lot_id;
ALTER TABLE material_dictionary DROP COLUMN IF EXISTS odoo_uom_id;
ALTER TABLE material_dictionary DROP COLUMN IF EXISTS odoo_product_id;
DROP INDEX IF EXISTS uniq_purchase_orders_odoo_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_id;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
