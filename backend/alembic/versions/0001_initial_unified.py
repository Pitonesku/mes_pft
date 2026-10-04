"""initial unified MES schema

Revision ID: 0001
Revises:
Create Date: 2026-10-03

Creates the unified domain tables added to models.py. The legacy tables (roles,
users, machines, purchase_orders, production_reports, the shift template, ...) are
already managed by Base.metadata.create_all() at startup and migrate_db.py, so
they are intentionally out of scope for this first migration.

NOTE: the legacy shift *template* table is still named ``shifts``. This migration
creates the aggregate as ``shift_sessions`` to avoid a collision. A later
migration will rename ``shifts`` -> ``shift_templates`` and ``shift_sessions`` ->
``shifts`` in one coordinated step.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS shift_sessions (
    id BIGSERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    operator_id INTEGER NULL REFERENCES users(id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    plant_tz VARCHAR(50) NOT NULL DEFAULT 'Europe/Budapest',
    source VARCHAR(20) NOT NULL DEFAULT 'tablet',
    client_shift_id VARCHAR(64) UNIQUE NULL,
    closed_at TIMESTAMPTZ NULL,
    closed_by INTEGER NULL REFERENCES users(id),
    time_confidence VARCHAR(20) NULL,
    legacy_report_key VARCHAR(100) NULL
);
CREATE INDEX IF NOT EXISTS ix_shift_sessions_machine_started
    ON shift_sessions (machine_id, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_shift_per_machine
    ON shift_sessions (machine_id) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS production_runs (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    seq INTEGER NOT NULL,
    po_id INTEGER NULL REFERENCES purchase_orders(id),
    mo_ref VARCHAR(100) NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    spec_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    odoo_mo_id INTEGER NULL,
    UNIQUE (shift_id, seq)
);

CREATE TABLE IF NOT EXISTS machine_aliases (
    id SERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    source VARCHAR(50) NOT NULL,
    alias_field VARCHAR(50) NOT NULL,
    alias_value VARCHAR(100) NOT NULL,
    valid_from TIMESTAMPTZ NULL,
    valid_to TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS quality_specs (
    id SERIAL PRIMARY KEY,
    scope VARCHAR(20) NOT NULL DEFAULT 'default',
    machine_id INTEGER NULL REFERENCES machines(id),
    po_id INTEGER NULL REFERENCES purchase_orders(id),
    parameter VARCHAR(30) NOT NULL,
    nominal NUMERIC NULL,
    lower_limit NUMERIC NULL,
    upper_limit NUMERIC NULL,
    reject_multiplier NUMERIC NOT NULL DEFAULT 3,
    rod_count INTEGER NOT NULL DEFAULT 100,
    report_unit VARCHAR(20) NOT NULL DEFAULT '',
    report_scale NUMERIC NOT NULL DEFAULT 1,
    decimals INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS quality_samples (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NULL REFERENCES shift_sessions(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    machine_id INTEGER NULL REFERENCES machines(id),
    link_status VARCHAR(30) NOT NULL DEFAULT 'NO_SHIFT',
    link_source VARCHAR(20) NOT NULL DEFAULT 'auto',
    kind VARCHAR(20) NOT NULL DEFAULT 'PRODUCTION',
    source_instrument_id VARCHAR(50) NULL,
    source_maker VARCHAR(50) NULL,
    source_team VARCHAR(50) NULL,
    sample_id VARCHAR(100) NULL,
    mo_ref VARCHAR(100) NULL,
    brand VARCHAR(100) NULL,
    operator VARCHAR(100) NULL,
    comments TEXT NULL,
    produced_at TIMESTAMPTZ NOT NULL,
    batch_started_at TIMESTAMPTZ NULL,
    batch_ended_at TIMESTAMPTZ NULL,
    rods_declared INTEGER NULL,
    file_sha256 VARCHAR(64) UNIQUE NULL,
    file_md5 VARCHAR(32) NULL
);
CREATE INDEX IF NOT EXISTS ix_quality_samples_shift ON quality_samples (shift_id);
CREATE INDEX IF NOT EXISTS ix_quality_samples_machine ON quality_samples (machine_id, produced_at);

CREATE TABLE IF NOT EXISTS quality_measurements (
    id BIGSERIAL PRIMARY KEY,
    sample_id BIGINT NOT NULL REFERENCES quality_samples(id),
    shift_id BIGINT NULL REFERENCES shift_sessions(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    machine_id INTEGER NULL REFERENCES machines(id),
    measured_at TIMESTAMPTZ NOT NULL,
    rod_no INTEGER NOT NULL,
    pd NUMERIC NULL,
    weight NUMERIC NULL,
    diameter NUMERIC NULL,
    ovality NUMERIC NULL,
    roundness NUMERIC NULL,
    shape NUMERIC NULL,
    hardness NUMERIC NULL
);
CREATE INDEX IF NOT EXISTS ix_quality_measurements_shift ON quality_measurements (shift_id);
CREATE INDEX IF NOT EXISTS ix_quality_measurements_relink
    ON quality_measurements (machine_id, measured_at) WHERE shift_id IS NULL;

CREATE TABLE IF NOT EXISTS material_logs (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    material_id INTEGER NULL REFERENCES material_dictionary(id),
    category VARCHAR(50) NOT NULL,
    batch_no VARCHAR(100) NULL,
    qty_kg NUMERIC(12,3) NOT NULL DEFAULT 0,
    source VARCHAR(30) NOT NULL DEFAULT 'legacy'
);

CREATE TABLE IF NOT EXISTS scrap_logs (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    reason_code VARCHAR(50) NOT NULL DEFAULT 'UNSPECIFIED',
    qty_kg NUMERIC(12,3) NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS ingestion_files (
    id BIGSERIAL PRIMARY KEY,
    sha256 VARCHAR(64) NOT NULL UNIQUE,
    md5 VARCHAR(32) NULL,
    filename VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processed',
    error TEXT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    sample_id BIGINT NULL REFERENCES quality_samples(id),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS shift_quality_stats (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    run_id BIGINT NULL REFERENCES production_runs(id),
    version INTEGER NOT NULL DEFAULT 1,
    parameter VARCHAR(30) NOT NULL,
    n INTEGER NOT NULL DEFAULT 0,
    n_rejected INTEGER NOT NULL DEFAULT 0,
    mean NUMERIC NULL,
    sd_samp NUMERIC NULL,
    sd_pop NUMERIC NULL,
    min NUMERIC NULL,
    max NUMERIC NULL,
    target NUMERIC NULL,
    lsl NUMERIC NULL,
    usl NUMERIC NULL,
    n_out_of_spec INTEGER NOT NULL DEFAULT 0,
    pass_rate NUMERIC NULL,
    status VARCHAR(20) NULL
);

CREATE TABLE IF NOT EXISTS shift_summaries (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    version INTEGER NOT NULL DEFAULT 1,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    input_fingerprint VARCHAR(100) NULL,
    is_stale BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS odoo_outbox (
    id BIGSERIAL PRIMARY KEY,
    aggregate_type VARCHAR(30) NOT NULL,
    aggregate_id BIGINT NOT NULL,
    shift_summary_version INTEGER NULL,
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NULL,
    odoo_model VARCHAR(100) NULL,
    odoo_id INTEGER NULL,
    last_error TEXT NULL
);
"""

_DOWN = """
DROP TABLE IF EXISTS odoo_outbox, shift_summaries, shift_quality_stats,
    ingestion_files, scrap_logs, material_logs, quality_measurements,
    quality_samples, quality_specs, machine_aliases, production_runs,
    shift_sessions CASCADE;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)

