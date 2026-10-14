"""add manual_quality_checks for in-process operator QC logging

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09

The tablet "Start Shift" lifecycle lets an operator record manual QC checks
(weight, length, visual flags) against an open shift and its active MO run.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS manual_quality_checks (
    id BIGSERIAL PRIMARY KEY,
    shift_id BIGINT NOT NULL REFERENCES shift_sessions(id),
    mo_id BIGINT NULL REFERENCES production_runs(id),
    operator_id INTEGER NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sample_weight NUMERIC NULL,
    length_mm NUMERIC NULL,
    glue_seam_ok BOOLEAN NOT NULL DEFAULT TRUE,
    cut_quality_ok BOOLEAN NOT NULL DEFAULT TRUE,
    visual_appearance_ok BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_manual_quality_checks_shift_id ON manual_quality_checks (shift_id);
CREATE INDEX IF NOT EXISTS ix_manual_quality_checks_mo_id ON manual_quality_checks (mo_id);
"""

_DOWN = """
DROP TABLE IF EXISTS manual_quality_checks;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
