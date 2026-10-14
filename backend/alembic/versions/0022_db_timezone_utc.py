"""enforce UTC as the database session timezone

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-13

PostgreSQL's ``now()`` and TIMESTAMP defaults use the database/session timezone.
A host provisioned with a non-UTC default (e.g. US/Pacific) silently corrupts every
``func.now()`` default. This migration pins the *database-level* default to UTC so
any freshly-created database is correct the moment migrations run. The SQLAlchemy
pool in ``app/database.py`` also forces ``timezone=utc`` per connection, which is
the authoritative runtime enforcement.
"""

from alembic import op
from sqlalchemy import text

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _alter_db_timezone(sql: str) -> None:
    # ALTER DATABASE cannot run inside a transaction block, so open a fresh
    # autocommit connection (separate from Alembic's migration transaction).
    engine = op.get_bind().engine
    with engine.connect() as conn:
        autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
        dbname = autocommit.execute(text("SELECT current_database()")).scalar()
        autocommit.execute(text(f'ALTER DATABASE "{dbname}" {sql}'))


def upgrade() -> None:
    _alter_db_timezone("SET timezone TO 'UTC'")


def downgrade() -> None:
    _alter_db_timezone("RESET timezone")
