"""order completion status + final rollup snapshots

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-13

A manufacturing run is rarely exact, so an order needs an explicit lifecycle end
instead of the operator manually hiding it. This migration adds:

  * purchase_orders.completion_status  - active | completed | cancelled
  * purchase_orders.completed_at/by    - audit trail of the finalize action
  * purchase_orders.final_*            - immutable cumulative snapshots written
                                         once at finalize (production + materials
                                         + consolidated quality) so the summary
                                         certificate never drifts with later edits
  * purchase_orders.odoo_summary_attachment_id - the ir.attachment created on the
                                         root MO when the summary PDF is pushed
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS completion_status VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS completed_by VARCHAR(50) NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS final_boxes BIGINT NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS final_rods BIGINT NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS final_waste_kg NUMERIC NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS final_materials JSONB NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS final_quality JSONB NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_summary_attachment_id INTEGER NULL;
CREATE INDEX IF NOT EXISTS ix_purchase_orders_completion_status ON purchase_orders (completion_status);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_purchase_orders_completion_status;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_summary_attachment_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_quality;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_materials;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_waste_kg;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_rods;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_boxes;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS completed_by;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS completed_at;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS completion_status;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
