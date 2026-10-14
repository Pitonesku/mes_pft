"""order material origin tracking

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07

Adds data-origin tracking (source: odoo | local) for orders and materials, and
a small key-value ``system_settings`` table for the Odoo integration mode toggle.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'local';
ALTER TABLE material_dictionary ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'local';

CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DOWN = """
DROP TABLE IF EXISTS system_settings;
ALTER TABLE material_dictionary DROP COLUMN IF EXISTS source;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS source;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
