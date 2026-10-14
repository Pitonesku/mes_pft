"""run-level machine, report<->run links, QC check binding, run change log

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-10

Option 2 of the shift model: a *shift* is an operator session, a *production run*
is "one MO on one machine over an interval". The machine therefore lives on the
run (``production_runs.machine_id``); ``shift_sessions.machine_id`` keeps meaning
"the machine the shift is on right now".

Additive only (invariant 2):
  * production_runs.machine_id            (backfilled from the shift, NULLable)
  * production_reports.shift_id / run_id  (one report per MO run; NULLable)
  * manual_quality_checks snapshot / verdict / void / idempotency columns, and the
    three visual toggles become tri-state (NULL = "not checked")
  * run_change_log                         (audit trail for MO / machine changes)

Data repair (fills NULLs only, never overwrites a value): runs that are still
OPEN although their shift has ended are closed at the shift's end time. Without
this, the new "one open run per machine" unique index could not be created.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_UP = """
-- 1. repair phantom open runs (shift already ended)
UPDATE production_runs r
   SET ended_at = s.ended_at
  FROM shift_sessions s
 WHERE s.id = r.shift_id AND s.ended_at IS NOT NULL AND r.ended_at IS NULL;
UPDATE production_runs SET status = 'CLOSED'
 WHERE ended_at IS NOT NULL AND status = 'OPEN';

-- 2. machine on the run
ALTER TABLE production_runs ADD COLUMN IF NOT EXISTS machine_id INTEGER NULL REFERENCES machines(id);
UPDATE production_runs r
   SET machine_id = s.machine_id
  FROM shift_sessions s
 WHERE s.id = r.shift_id AND r.machine_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_production_runs_machine_id ON production_runs (machine_id);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_run_per_machine
    ON production_runs (machine_id) WHERE ended_at IS NULL;

-- 3. report <-> shift / run
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS shift_id BIGINT NULL REFERENCES shift_sessions(id);
ALTER TABLE production_reports ADD COLUMN IF NOT EXISTS run_id BIGINT NULL REFERENCES production_runs(id);
CREATE INDEX IF NOT EXISTS ix_production_reports_shift_id ON production_reports (shift_id);
CREATE INDEX IF NOT EXISTS ix_production_reports_run_id ON production_reports (run_id);
UPDATE production_reports rep
   SET run_id = pr.id, shift_id = pr.shift_id
  FROM production_runs pr
 WHERE pr.report_id = rep.id AND rep.run_id IS NULL;

-- 4. manual QC checks: bind to machine / MO at the time of the check
ALTER TABLE manual_quality_checks
    ADD COLUMN IF NOT EXISTS machine_id INTEGER NULL REFERENCES machines(id),
    ADD COLUMN IF NOT EXISTS po_id INTEGER NULL REFERENCES purchase_orders(id),
    ADD COLUMN IF NOT EXISTS mo_ref VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS sample_rods INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS verdicts JSONB NULL,
    ADD COLUMN IF NOT EXISTS overall_status VARCHAR(10) NULL,
    ADD COLUMN IF NOT EXISTS measured_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS client_check_id VARCHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS voided_by INTEGER NULL REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS void_reason TEXT NULL;
ALTER TABLE manual_quality_checks
    ALTER COLUMN glue_seam_ok DROP NOT NULL,
    ALTER COLUMN glue_seam_ok DROP DEFAULT,
    ALTER COLUMN cut_quality_ok DROP NOT NULL,
    ALTER COLUMN cut_quality_ok DROP DEFAULT,
    ALTER COLUMN visual_appearance_ok DROP NOT NULL,
    ALTER COLUMN visual_appearance_ok DROP DEFAULT;
UPDATE manual_quality_checks c
   SET machine_id = r.machine_id, po_id = r.po_id, mo_ref = r.mo_ref
  FROM production_runs r
 WHERE r.id = c.mo_id AND c.machine_id IS NULL;
UPDATE manual_quality_checks SET measured_at = created_at WHERE measured_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_quality_checks_client_id
    ON manual_quality_checks (client_check_id) WHERE client_check_id IS NOT NULL;

-- 5. audit trail
CREATE TABLE IF NOT EXISTS run_change_log (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES production_runs(id),
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    user_id INTEGER NULL REFERENCES users(id),
    action VARCHAR(30) NOT NULL,
    old_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_run_change_log_run_id ON run_change_log (run_id);
CREATE INDEX IF NOT EXISTS ix_run_change_log_shift_id ON run_change_log (shift_id);
"""

# The phantom-run repair in step 1 is intentionally not reversed.
_DOWN = """
DROP TABLE IF EXISTS run_change_log;
DROP INDEX IF EXISTS uq_manual_quality_checks_client_id;
ALTER TABLE manual_quality_checks
    DROP COLUMN IF EXISTS void_reason,
    DROP COLUMN IF EXISTS voided_by,
    DROP COLUMN IF EXISTS voided_at,
    DROP COLUMN IF EXISTS client_check_id,
    DROP COLUMN IF EXISTS measured_at,
    DROP COLUMN IF EXISTS overall_status,
    DROP COLUMN IF EXISTS verdicts,
    DROP COLUMN IF EXISTS sample_rods,
    DROP COLUMN IF EXISTS mo_ref,
    DROP COLUMN IF EXISTS po_id,
    DROP COLUMN IF EXISTS machine_id;
DROP INDEX IF EXISTS ix_production_reports_run_id;
DROP INDEX IF EXISTS ix_production_reports_shift_id;
ALTER TABLE production_reports DROP COLUMN IF EXISTS run_id;
ALTER TABLE production_reports DROP COLUMN IF EXISTS shift_id;
DROP INDEX IF EXISTS one_open_run_per_machine;
DROP INDEX IF EXISTS ix_production_runs_machine_id;
ALTER TABLE production_runs DROP COLUMN IF EXISTS machine_id;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
