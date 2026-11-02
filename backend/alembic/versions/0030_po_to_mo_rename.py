"""po_number -> mo_number column rename (Manufacturing Order terminology)

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-29

Renames purchase_orders.po_number and production_reports.po_number to
mo_number (ROADMAP po->mo, step 2). The BI views from migration 0002 reference
po.po_number, so they are recreated against the new column.

Backward compatibility is preserved at the API layer: the ORM keeps a
``po_number`` property alias and the legacy report schemas keep serializing
``po_number``, so old tablet APKs keep working until they auto-update.
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_VIEWS_DOWN = """
DROP VIEW IF EXISTS v_worker_status;
DROP VIEW IF EXISTS v_run_stats;
DROP VIEW IF EXISTS v_quality_rods;
"""

_VIEWS_UP = """
CREATE OR REPLACE VIEW v_quality_rods AS
SELECT
    qm.id AS measurement_id,
    qm.sample_id,
    qm.shift_id,
    qm.run_id,
    qm.machine_id,
    m.name AS machine_name,
    qm.measured_at,
    qm.rod_no,
    qm.pd,
    qm.weight,
    qm.diameter,
    qm.ovality,
    qm.roundness,
    qm.shape,
    qm.hardness,
    ss.started_at AS shift_started_at,
    ss.ended_at AS shift_ended_at,
    pr.mo_ref,
    pr.po_id,
    po.mo_number,
    pd_spec.nominal AS pd_target,
    pd_spec.lower_limit AS pd_lsl,
    pd_spec.upper_limit AS pd_usl,
    dia_spec.nominal AS diameter_target,
    dia_spec.lower_limit AS diameter_lsl,
    dia_spec.upper_limit AS diameter_usl,
    wt_spec.nominal AS weight_target,
    wt_spec.lower_limit AS weight_lsl,
    wt_spec.upper_limit AS weight_usl
FROM quality_measurements qm
LEFT JOIN machines m ON m.id = qm.machine_id
LEFT JOIN shift_sessions ss ON ss.id = qm.shift_id
LEFT JOIN production_runs pr ON pr.id = qm.run_id
LEFT JOIN purchase_orders po ON po.id = pr.po_id
LEFT JOIN quality_specs pd_spec
       ON pd_spec.parameter = 'pd' AND pd_spec.po_id = pr.po_id
LEFT JOIN quality_specs dia_spec
       ON dia_spec.parameter = 'diameter' AND dia_spec.po_id = pr.po_id
LEFT JOIN quality_specs wt_spec
       ON wt_spec.parameter = 'weight' AND wt_spec.po_id = pr.po_id;

CREATE OR REPLACE VIEW v_run_stats AS
SELECT
    qm.run_id,
    pr.shift_id,
    pr.mo_ref,
    pr.po_id,
    po.mo_number,
    qm.machine_id,
    COUNT(*) AS rods_total,
    AVG(qm.pd) AS pd_mean,
    STDDEV_SAMP(qm.pd) AS pd_sd_samp,
    MIN(qm.pd) AS pd_min,
    MAX(qm.pd) AS pd_max,
    AVG(qm.diameter) AS diameter_mean,
    STDDEV_SAMP(qm.diameter) AS diameter_sd_samp,
    MIN(qm.diameter) AS diameter_min,
    MAX(qm.diameter) AS diameter_max,
    AVG(qm.weight) AS weight_mean,
    STDDEV_SAMP(qm.weight) AS weight_sd_samp,
    MIN(qm.weight) AS weight_min,
    MAX(qm.weight) AS weight_max
FROM quality_measurements qm
JOIN production_runs pr ON pr.id = qm.run_id
LEFT JOIN purchase_orders po ON po.id = pr.po_id
GROUP BY qm.run_id, pr.shift_id, pr.mo_ref, pr.po_id, po.mo_number, qm.machine_id;

CREATE OR REPLACE VIEW v_worker_status AS
SELECT
    1 AS id,
    MAX(COALESCE(processed_at, first_seen_at)) AS last_seen,
    COUNT(*) FILTER (WHERE status = 'processed') AS processed_count,
    COUNT(*) FILTER (WHERE status = 'error') AS error_count,
    COUNT(*) AS total_files
FROM ingestion_files;
"""


def upgrade() -> None:
    op.execute(_VIEWS_DOWN)
    op.execute("ALTER TABLE purchase_orders RENAME COLUMN po_number TO mo_number")
    op.execute("ALTER TABLE production_reports RENAME COLUMN po_number TO mo_number")
    op.execute(_VIEWS_UP)


def downgrade() -> None:
    op.execute(_VIEWS_DOWN)
    op.execute("ALTER TABLE purchase_orders RENAME COLUMN mo_number TO po_number")
    op.execute("ALTER TABLE production_reports RENAME COLUMN mo_number TO po_number")
    op.execute(_VIEWS_UP.replace("po.mo_number", "po.po_number"))
