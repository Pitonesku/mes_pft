"""quality settings defaults

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

Adds the singleton ``quality_settings`` table holding factory-wide quality
defaults: per-parameter tolerance (diameter, pressure drop) and the standard
deviation status thresholds (warn / fail) used by the quality overview and the
live-quality endpoints.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS quality_settings (
    id SERIAL PRIMARY KEY,
    diameter_tolerance NUMERIC NOT NULL DEFAULT 0.03,
    pd_tolerance NUMERIC NOT NULL DEFAULT 20,
    pd_sd_warn NUMERIC NOT NULL DEFAULT 12,
    pd_sd_fail NUMERIC NOT NULL DEFAULT 15,
    dia_sd_warn NUMERIC NOT NULL DEFAULT 0.013,
    dia_sd_fail NUMERIC NOT NULL DEFAULT 0.015
);
"""

_DOWN = """
DROP TABLE IF EXISTS quality_settings;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
