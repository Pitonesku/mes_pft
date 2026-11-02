"""quality management: quarantine ledger, NCR lifecycle, RBAC

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-28

* production_reports.quarantine_boxes (INTEGER NOT NULL DEFAULT 0)
    finished boxes isolated pending engineering inspection; excluded from
    boxes_produced and waste_kg until resolved.
* quarantine_resolutions (SCRAP | RELEASE)
    async resolution of the quarantine balance for one order. Balance =
    SUM(reports.quarantine_boxes) - SUM(non-voided resolutions.boxes).
* non_conformity_reports + ncr_status_logs
    NCR lifecycle (OPEN -> IN_PROGRESS -> CLOSED) with an immutable audit trail.
* roles.users can_manage_quality (BOOLEAN)
    RBAC grant for creating/closing NCRs and posting resolutions.
* purchase_orders.final_quarantine_boxes / final_scrap_boxes / final_scrap_kg
    immutable snapshots written at order finalize; post-close resolutions never
    mutate them.
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE production_reports
    ADD COLUMN IF NOT EXISTS quarantine_boxes INTEGER NOT NULL DEFAULT 0;

ALTER TABLE roles
    ADD COLUMN IF NOT EXISTS can_manage_quality BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS can_manage_quality BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS final_quarantine_boxes BIGINT NULL;
ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS final_scrap_boxes BIGINT NULL;
ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS final_scrap_kg NUMERIC NULL;

CREATE TABLE IF NOT EXISTS non_conformity_reports (
    id BIGSERIAL PRIMARY KEY,
    ncr_number VARCHAR(50) UNIQUE NULL,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    mo_ref VARCHAR(100) NULL,
    doc_seq INTEGER NOT NULL,
    run_id BIGINT NULL REFERENCES production_runs(id),
    machine_id INTEGER NULL REFERENCES machines(id),
    description TEXT NOT NULL,
    corrective_action TEXT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'MINOR',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_by INTEGER NULL REFERENCES users(id),
    closed_at TIMESTAMPTZ NULL,
    closing_remarks TEXT NULL,
    UNIQUE (po_id, doc_seq)
);
CREATE INDEX IF NOT EXISTS ix_non_conformity_reports_po
    ON non_conformity_reports (po_id);
CREATE INDEX IF NOT EXISTS ix_non_conformity_reports_status
    ON non_conformity_reports (status);
CREATE INDEX IF NOT EXISTS ix_non_conformity_reports_machine
    ON non_conformity_reports (machine_id);

CREATE TABLE IF NOT EXISTS ncr_status_logs (
    id BIGSERIAL PRIMARY KEY,
    ncr_id BIGINT NOT NULL REFERENCES non_conformity_reports(id),
    from_status VARCHAR(20) NULL,
    to_status VARCHAR(20) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    username VARCHAR(100) NOT NULL,
    remarks TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ncr_status_logs_ncr ON ncr_status_logs (ncr_id);

CREATE TABLE IF NOT EXISTS quarantine_resolutions (
    id BIGSERIAL PRIMARY KEY,
    doc_number VARCHAR(50) UNIQUE NULL,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    mo_ref VARCHAR(100) NULL,
    doc_seq INTEGER NOT NULL,
    kind VARCHAR(10) NOT NULL,               -- SCRAP | RELEASE
    boxes INTEGER NOT NULL,
    dry_weight_kg NUMERIC(12, 3) NULL,       -- SCRAP only
    reason_code VARCHAR(50) NULL,
    notes TEXT NULL,
    ncr_id BIGINT NULL REFERENCES non_conformity_reports(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    odoo_sync_status VARCHAR(20) NOT NULL DEFAULT 'local',  -- local | pending | synced | error | shadow
    odoo_model VARCHAR(100) NULL,
    odoo_id INTEGER NULL,
    voided_at TIMESTAMPTZ NULL,
    voided_by INTEGER NULL REFERENCES users(id),
    void_reason TEXT NULL,
    UNIQUE (po_id, doc_seq)
);
CREATE INDEX IF NOT EXISTS ix_quarantine_resolutions_po
    ON quarantine_resolutions (po_id);
CREATE INDEX IF NOT EXISTS ix_quarantine_resolutions_ncr
    ON quarantine_resolutions (ncr_id);
"""

_DOWN = """
DROP TABLE IF EXISTS quarantine_resolutions;
DROP TABLE IF EXISTS ncr_status_logs;
DROP TABLE IF EXISTS non_conformity_reports;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_scrap_kg;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_scrap_boxes;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS final_quarantine_boxes;
ALTER TABLE users DROP COLUMN IF EXISTS can_manage_quality;
ALTER TABLE roles DROP COLUMN IF EXISTS can_manage_quality;
ALTER TABLE production_reports DROP COLUMN IF EXISTS quarantine_boxes;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
