"""Frozen migrate_db.py startup effects moved into Alembic (A3)

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-29

Replaces the two idempotent runtime migrators that used to run at every
startup (lifespan) outside Alembic:

* migrate_roles_and_users: rename roles.name -> role_name, add the permission
  columns, normalize admin/manager grants, add missing users columns and
  rename users.role -> tg_role.
* migrate_report_idempotency: add production_reports.client_report_id plus the
  partial unique index.

Deliberate change: the legacy auto-reset of plain-text passwords to a fixed
'1111' is NOT replicated. Plain-text hashes are rejected by the bcrypt-only
verifier anyway, and the explicit remediation path remains the operator script
app/scripts/fix_plaintext_passwords.py (see docs/AUTHENTICATION.md).
"""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_ROLE_PERMISSIONS = (
    "can_create_po", "can_edit_po", "can_edit_report",
    "can_manage_users", "can_setup_machines", "can_view_all_reports",
)

_USER_COLUMNS = {
    "is_inactive": "BOOLEAN NOT NULL DEFAULT FALSE",
    "created_at": "TIMESTAMP DEFAULT now()",
    "telegram_id": "BIGINT",
    "tg_role": "VARCHAR(50) DEFAULT 'user'",
    "password_pin": "VARCHAR(255)",
    "can_use_ai": "BOOLEAN NOT NULL DEFAULT FALSE",
    "can_edit_report": "BOOLEAN NOT NULL DEFAULT FALSE",
    "can_create_po": "BOOLEAN NOT NULL DEFAULT FALSE",
    "can_edit_po": "BOOLEAN NOT NULL DEFAULT FALSE",
}


def upgrade() -> None:
    # --- roles -----------------------------------------------------------------
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='roles' AND column_name='name')
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='roles' AND column_name='role_name') THEN
                ALTER TABLE roles RENAME COLUMN name TO role_name;
            END IF;
        END $$;
    """)
    for col in _ROLE_PERMISSIONS:
        op.execute(
            f"ALTER TABLE roles ADD COLUMN IF NOT EXISTS {col} "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    # Full permissions for admin/superadmin roles.
    op.execute("""
        UPDATE roles
        SET can_create_po=TRUE, can_edit_po=TRUE, can_edit_report=TRUE,
            can_manage_users=TRUE, can_setup_machines=TRUE, can_view_all_reports=TRUE
        WHERE LOWER(role_name) IN ('superadmin', 'admin')
    """)
    # Manager: orders/reports only - no user or machine management.
    op.execute("""
        UPDATE roles
        SET can_create_po=TRUE, can_edit_po=TRUE, can_edit_report=TRUE,
            can_manage_users=FALSE, can_setup_machines=FALSE, can_view_all_reports=TRUE
        WHERE LOWER(role_name) = 'manager'
    """)

    # --- users -----------------------------------------------------------------
    for col, definition in _USER_COLUMNS.items():
        op.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='users' AND column_name='role')
               AND EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='users' AND column_name='tg_role') THEN
                UPDATE users SET tg_role = role WHERE tg_role IS NULL OR tg_role = 'user';
                ALTER TABLE users DROP COLUMN role;
            ELSIF EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='users' AND column_name='role')
              AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name='users' AND column_name='tg_role') THEN
                ALTER TABLE users RENAME COLUMN role TO tg_role;
            END IF;
        END $$;
    """)

    # --- production_reports idempotency ----------------------------------------
    op.execute(
        "ALTER TABLE production_reports "
        "ADD COLUMN IF NOT EXISTS client_report_id VARCHAR(64)"
    )
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_production_reports_client_id
        ON production_reports (client_report_id)
        WHERE client_report_id IS NOT NULL
    """)


def downgrade() -> None:
    # All effects are additive/idempotent and already existed in production
    # before this migration; nothing is removed on downgrade.
    pass
