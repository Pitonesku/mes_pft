"""odoo shadow log

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07

Phase 3: shadow mode. When ODOO_SHADOW_MODE is on, the dispatcher performs every
Odoo READ for real but only records the WRITES it would have made. One row per
dispatched run; additive table, nothing existing is touched (invariants #2, #3).
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS odoo_shadow_log (
    id BIGSERIAL PRIMARY KEY,
    outbox_id BIGINT NULL REFERENCES odoo_outbox(id) ON DELETE SET NULL,
    run_id BIGINT NULL REFERENCES production_runs(id) ON DELETE SET NULL,
    odoo_mo_id INTEGER NULL,
    link_only BOOLEAN NOT NULL DEFAULT FALSE,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_odoo_shadow_log_outbox ON odoo_shadow_log (outbox_id);
CREATE INDEX IF NOT EXISTS ix_odoo_shadow_log_run ON odoo_shadow_log (run_id);
"""

_DOWN = """
DROP INDEX IF EXISTS ix_odoo_shadow_log_run;
DROP INDEX IF EXISTS ix_odoo_shadow_log_outbox;
DROP TABLE IF EXISTS odoo_shadow_log;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
