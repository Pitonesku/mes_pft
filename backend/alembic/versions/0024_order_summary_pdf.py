"""add Flutter-generated order summary PDF columns

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-14

* purchase_orders.order_summary_pdf_base64   - the Flutter-generated consolidated
  Order Summary PDF (primary source of truth). The ReportLab
  render_order_summary_pdf() remains only as a fallback when this is NULL
  (backend-initiated finalize with no client in the loop).
* purchase_orders.order_summary_pdf_filename - optional original filename.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS order_summary_pdf_base64 TEXT NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS order_summary_pdf_filename VARCHAR(255) NULL;
"""

_DOWN = """
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS order_summary_pdf_filename;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS order_summary_pdf_base64;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
