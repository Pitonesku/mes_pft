"""drop the never-used shift_quality_stats table

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-10

``shift_quality_stats`` was created in 0001 but nothing ever wrote to or read from
it (the versioned ``shift_summaries`` JSON is the single aggregation output). The
table is empty; the DROP is guarded so it never removes a table that holds rows.
The downgrade recreates the empty table.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_UP = """
DO $$
BEGIN
    IF to_regclass('public.shift_quality_stats') IS NOT NULL THEN
        IF (SELECT count(*) FROM shift_quality_stats) = 0 THEN
            DROP TABLE shift_quality_stats;
        ELSE
            RAISE NOTICE 'shift_quality_stats is not empty - left in place';
        END IF;
    END IF;
END $$;
"""

_DOWN = """
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
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
