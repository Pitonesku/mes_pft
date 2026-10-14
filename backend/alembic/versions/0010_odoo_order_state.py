"""odoo order state

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07

Phase 2: inbound lifecycle. Records the state of the Odoo MO chain per order so
MES notices cancelled / completed / drifting MOs. Additive and nullable
(invariants #2, #3).

  * purchase_orders.odoo_state      - open | done | cancel | check | missing
  * purchase_orders.odoo_synced_at  - last successful chain reconciliation
  * purchase_orders.odoo_qty_drift  - Odoo root qty minus MES target_qty (info only)
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_state VARCHAR(20) NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_synced_at TIMESTAMPTZ NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_qty_drift NUMERIC NULL;
CREATE INDEX IF NOT EXISTS ix_purchase_orders_odoo_state ON purchase_orders (odoo_state);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_purchase_orders_odoo_state;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_qty_drift;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_synced_at;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_state;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
