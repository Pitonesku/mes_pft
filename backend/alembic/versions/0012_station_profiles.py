"""add station_profiles for per-station parser mapping

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08

Each station may emit measurement files with a different column order or a
different parameter set (e.g. no weight). ``station_profiles`` holds the parser
overrides keyed by a station identifier resolved from the file header.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS station_profiles (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    match_key VARCHAR(50) NOT NULL,
    match_value VARCHAR(100) NOT NULL,
    data_start_row INTEGER NULL,
    encoding VARCHAR(20) NULL,
    mo_field VARCHAR(30) NULL,
    metadata_map JSONB NULL,
    column_map JSONB NULL,
    valid_from TIMESTAMPTZ NULL,
    valid_to TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_station_profiles_lookup
    ON station_profiles (source, match_key, match_value);
"""

_DOWN = """
DROP TABLE IF EXISTS station_profiles;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
