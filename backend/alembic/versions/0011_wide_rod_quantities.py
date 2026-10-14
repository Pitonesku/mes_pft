"""widen rod quantity columns to bigint

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08

Rod quantities can legitimately exceed 2 147 483 647 (int4) because Odoo MOs are
often expressed in a "1000pcs" unit: an MO of 10 000 000 x 1000pcs is 10 billion
rods, and the MES stores quantities in single rods. The Odoo -> MES push failed
with NumericValueOutOfRange as soon as such an MO arrived.

Widening INTEGER -> BIGINT keeps every existing value and is non-destructive
(invariant #2). Columns:

  * purchase_orders.target_qty    - planned rods for the order
  * purchase_orders.produced_qty  - accumulated produced rods
  * production_reports.produced_rods  - rods reported for one shift
  * production_reports.machine_counter - machine odometer reading
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ALTER COLUMN target_qty TYPE BIGINT;
ALTER TABLE purchase_orders ALTER COLUMN produced_qty TYPE BIGINT;
ALTER TABLE production_reports ALTER COLUMN produced_rods TYPE BIGINT;
ALTER TABLE production_reports ALTER COLUMN machine_counter TYPE BIGINT;
"""

_DOWN = """
ALTER TABLE production_reports ALTER COLUMN machine_counter TYPE INTEGER;
ALTER TABLE production_reports ALTER COLUMN produced_rods TYPE INTEGER;
ALTER TABLE purchase_orders ALTER COLUMN produced_qty TYPE INTEGER;
ALTER TABLE purchase_orders ALTER COLUMN target_qty TYPE INTEGER;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
