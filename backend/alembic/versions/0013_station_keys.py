"""add station_keys for long-lived ingest API keys

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-09

The push agent authenticates with a long-lived, revocable API key instead of an
interactive admin login. ``station_keys`` stores only the SHA-256 hash of each
key (plaintext is issued once by ``create_station_key`` and never persisted).
The ``station_ingest`` role/service account is seeded at app startup (seed.py).
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_UP = """
CREATE TABLE IF NOT EXISTS station_keys (
    id SERIAL PRIMARY KEY,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    label VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ NULL,
    user_id INTEGER NULL REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_station_keys_key_hash ON station_keys (key_hash);
"""

_DOWN = """
DROP TABLE IF EXISTS station_keys;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
