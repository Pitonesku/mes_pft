"""root mo hierarchy link fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07

Adds root Manufacturing Order link fields on purchase_orders for the Odoo
on-demand sync + backorder hierarchy resolution.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_mo_id INTEGER NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_mo_name VARCHAR(100) NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_linked_at TIMESTAMPTZ NULL;
CREATE INDEX IF NOT EXISTS ix_purchase_orders_odoo_mo_id ON purchase_orders (odoo_mo_id);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_purchase_orders_odoo_mo_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_linked_at;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_mo_name;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_mo_id;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
