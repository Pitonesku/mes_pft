"""MO identity, current open MO, sync mode and run->report link

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07

Phase 1 of the Odoo integration roadmap (additive, nullable/default-safe -
invariants #2 and #3):

  * purchase_orders.odoo_current_mo_id - the currently open MO of the Odoo
    backorder chain (odoo_mo_id stays the ROOT MO).
  * purchase_orders.sync_mode - 'full' (post completion to Odoo) or
    'link_only' (link + attach quality data, never touch stock). Existing rows
    default to 'link_only' so historical data can never be posted by accident;
    new open MOs arriving from Odoo are set to 'full' by the inbound handler.
  * production_runs.report_id - direct link to the operator production report
    that is the authoritative source of the produced quantity.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS odoo_current_mo_id INTEGER NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS sync_mode VARCHAR(20) NOT NULL DEFAULT 'link_only';

ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS report_id INTEGER NULL
    REFERENCES production_reports(id);
CREATE INDEX IF NOT EXISTS ix_production_runs_report_id ON production_runs (report_id);

INSERT INTO system_settings (key, value)
VALUES ('odoo_sync_from_date', '{"date": null}'::jsonb)
ON CONFLICT (key) DO NOTHING;
"""

_DOWN = """
DELETE FROM system_settings WHERE key = 'odoo_sync_from_date';
DROP INDEX IF EXISTS ix_production_runs_report_id;
ALTER TABLE production_runs DROP COLUMN IF EXISTS report_id;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS sync_mode;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS odoo_current_mo_id;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
