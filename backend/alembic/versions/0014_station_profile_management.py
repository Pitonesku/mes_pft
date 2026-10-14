"""extend station_profiles for the Settings -> Quality Stations UI

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09

Adds the human-facing management fields to ``station_profiles``:
  * label          - human station name
  * delivery_mode  - 'push' (agent) or 'pull' (network share)
  * watch_path     - network folder for pull-mode stations
  * station_key_id - link to the profile's active push-mode API key
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE station_profiles ADD COLUMN IF NOT EXISTS label VARCHAR(100) NULL;
ALTER TABLE station_profiles ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(10) NOT NULL DEFAULT 'push';
ALTER TABLE station_profiles ADD COLUMN IF NOT EXISTS watch_path VARCHAR(500) NULL;
ALTER TABLE station_profiles ADD COLUMN IF NOT EXISTS station_key_id INTEGER NULL REFERENCES station_keys(id);
"""

_DOWN = """
ALTER TABLE station_profiles DROP COLUMN IF EXISTS station_key_id;
ALTER TABLE station_profiles DROP COLUMN IF EXISTS watch_path;
ALTER TABLE station_profiles DROP COLUMN IF EXISTS delivery_mode;
ALTER TABLE station_profiles DROP COLUMN IF EXISTS label;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
