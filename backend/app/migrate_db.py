import os
import pathlib
import importlib
import bcrypt
import psycopg2

# ---------------------------------------------------------------------------
# Locate and load the .env file from the project root, regardless of CWD.
# Same robust approach used in database.py and main.py.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Load .env via the shared helper (searches repo root, backend/, then app/).
# ---------------------------------------------------------------------------
if __package__:
    config = importlib.import_module(f"{__package__}.config")
else:
    import config

ENV_PATH = config.load_env()
print(f"[MigrateDB] Loaded .env from: {ENV_PATH}")

# ---------------------------------------------------------------------------
# Validate required DB credentials — no silent fallbacks.
# ---------------------------------------------------------------------------
def _check_env(var: str) -> str:
    """Get a required environment variable or raise a self-diagnosing error."""
    value = os.getenv(var)
    if not value:
        env_exists = ENV_PATH.is_file()
        db_keys = {k: v for k, v in os.environ.items() if k.startswith("DB_")}
        masked = {}
        for k, v in db_keys.items():
            if "PASSWORD" in k:
                masked[k] = "***" if v else "(empty)"
            elif "USER" in k:
                masked[k] = v[:2] + "***" if len(v) > 2 else v
            else:
                masked[k] = v
        raise RuntimeError(
            f"{var} is not set.\n"
            f"  .env path: {ENV_PATH}\n"
            f"  File exists: {env_exists}\n"
            f"  Loaded DB_ vars: {masked if masked else '(none)'}\n"
            f"  Please configure {var} in your .env file."
        )
    return value

DB_USER = _check_env("DB_USER")
DB_PASSWORD = _check_env("DB_PASSWORD")
DB_HOST = _check_env("DB_HOST")
DB_PORT = _check_env("DB_PORT")
DB_NAME = _check_env("DB_NAME")


def get_conn():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
    )

def table_exists(cursor, table):
    cursor.execute("""
        SELECT EXISTS(
            SELECT 1
            FROM information_schema.tables
            WHERE table_name=%s AND table_schema='public'
        )
    """, (table,))
    return cursor.fetchone()[0]

def column_exists(cursor, table, column):
    cursor.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name=%s AND column_name=%s
    """, (table, column))
    return cursor.fetchone() is not None

def add_column(cursor, table, column_def):
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def migrate_roles_and_users(conn):
    """
    Migrates roles and users tables from the legacy init_db.py schema
    to the current SQLAlchemy model schema.

    Legacy roles table had only:  id, name
    Current model expects:        id, role_name, can_create_po, can_edit_po,
                                   can_edit_report, can_manage_users,
                                   can_setup_machines, can_view_all_reports

    Legacy users table was missing: is_inactive, created_at
    """
    with conn.cursor() as cur:
        # -- roles table ------------------------------------------------------
        if not table_exists(cur, "roles"):
            print("i  [Migrate] 'roles' table not found -- skipping roles migration.")
        else:
            # 1. Rename 'name' -> 'role_name' if old column still present
            if column_exists(cur, "roles", "name") and not column_exists(cur, "roles", "role_name"):
                cur.execute("ALTER TABLE roles RENAME COLUMN name TO role_name")
                print("ok [Migrate] roles.name  ->  roles.role_name  (renamed).")
            elif column_exists(cur, "roles", "role_name"):
                print("i  [Migrate] roles.role_name already exists -- skipping rename.")

            # 2. Add missing permission columns
            permission_columns = {
                "can_create_po":        "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_edit_po":          "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_edit_report":      "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_manage_users":     "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_setup_machines":   "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_view_all_reports": "BOOLEAN NOT NULL DEFAULT FALSE",
            }
            for col, definition in permission_columns.items():
                if not column_exists(cur, "roles", col):
                    cur.execute(f"ALTER TABLE roles ADD COLUMN {col} {definition}")
                    print(f"ok [Migrate] Added roles.{col}")

            # 3. Grant permissions by role. 'superadmin'/'admin' get full access.
            #    'manager' gets order/report permissions but NOT user management or
            #    machine setup — those are admin-only (granting them to managers made
            #    every manager a de-facto full admin).
            cur.execute("""
                UPDATE roles
                SET can_create_po        = TRUE,
                    can_edit_po          = TRUE,
                    can_edit_report      = TRUE,
                    can_manage_users     = TRUE,
                    can_setup_machines   = TRUE,
                    can_view_all_reports = TRUE
                WHERE LOWER(role_name) IN ('superadmin', 'admin')
            """)
            if cur.rowcount > 0:
                print(f"ok [Migrate] Full permissions granted to {cur.rowcount} admin role(s).")

            cur.execute("""
                UPDATE roles
                SET can_create_po        = TRUE,
                    can_edit_po          = TRUE,
                    can_edit_report      = TRUE,
                    can_manage_users     = FALSE,
                    can_setup_machines   = FALSE,
                    can_view_all_reports = TRUE
                WHERE LOWER(role_name) = 'manager'
            """)
            if cur.rowcount > 0:
                print("ok [Migrate] Manager role normalized (no user/machine management).")

        # -- users table ------------------------------------------------------
        if not table_exists(cur, "users"):
            print("i  [Migrate] 'users' table not found -- skipping users migration.")
        else:
            user_columns = {
                "is_inactive":     "BOOLEAN NOT NULL DEFAULT FALSE",
                "created_at":      "TIMESTAMP DEFAULT now()",
                "telegram_id":     "BIGINT",
                "tg_role":         "VARCHAR(50) DEFAULT 'user'",
                "password_pin":    "VARCHAR(255)",
                "can_use_ai":      "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_edit_report": "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_create_po":   "BOOLEAN NOT NULL DEFAULT FALSE",
                "can_edit_po":     "BOOLEAN NOT NULL DEFAULT FALSE",
            }
            for col, definition in user_columns.items():
                if not column_exists(cur, "users", col):
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                    print(f"ok [Migrate] Added users.{col}")

            # Rename legacy 'role' column to 'tg_role' if it still exists
            if column_exists(cur, "users", "role") and not column_exists(cur, "users", "tg_role"):
                cur.execute("ALTER TABLE users RENAME COLUMN role TO tg_role")
                print("ok [Migrate] users.role  ->  users.tg_role  (renamed).")
            elif column_exists(cur, "users", "role") and column_exists(cur, "users", "tg_role"):
                # Both exist — copy data from role to tg_role then drop old column
                cur.execute("UPDATE users SET tg_role = role WHERE tg_role IS NULL OR tg_role = 'user'")
                cur.execute("ALTER TABLE users DROP COLUMN role")
                print("ok [Migrate] Merged users.role into users.tg_role and dropped old column.")

            # 4. Migrate plain-text or empty passwords to bcrypt hashes (idempotent)
            cur.execute("SELECT id, username, password_hash FROM users")
            users_to_fix = []
            for row in cur.fetchall():
                uid, uname, pw = row
                pw_str = (pw or "").strip()
                # A valid bcrypt hash starts with $2b$ or $2a$ or $2y$
                if not pw_str or not (pw_str.startswith("$2b$") or pw_str.startswith("$2a$") or pw_str.startswith("$2y$")):
                    users_to_fix.append((uid, uname))

            if users_to_fix:
                default_pw = "1111"
                hashed = bcrypt.hashpw(default_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                for uid, uname in users_to_fix:
                    cur.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (hashed, uid),
                    )
                print(
                    f"!! [Migrate] WARNING: {len(users_to_fix)} user(s) had plain-text or empty passwords.\n"
                    f"!!            Their passwords have been RESET to '{default_pw}'.\n"
                    f"!!            Affected users: {', '.join(u[1] for u in users_to_fix)}\n"
                    f"!!            Please ask them to change their password immediately."
                )
            else:
                print("ok [Migrate] All user passwords are already bcrypt-hashed — no changes needed.")

    conn.commit()
    print("ok [Migrate] roles/users schema migration complete.")


def migrate_report_idempotency(conn):
    """Add client_report_id column + partial unique index to production_reports
    so duplicate submissions can be detected and rejected safely."""
    with conn.cursor() as cur:
        if not table_exists(cur, "production_reports"):
            print("i  [Migrate] 'production_reports' table not found -- skipping idempotency migration.")
            return

        if not column_exists(cur, "production_reports", "client_report_id"):
            cur.execute("ALTER TABLE production_reports ADD COLUMN client_report_id VARCHAR(64)")
            print("ok [Migrate] Added production_reports.client_report_id")

        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_production_reports_client_id
            ON production_reports (client_report_id)
            WHERE client_report_id IS NOT NULL
        """)
        print("ok [Migrate] Ensured unique index on production_reports.client_report_id")

    conn.commit()


def main():
    with get_conn() as conn:
        # 1. Migrate roles/users tables (legacy schema fix) first
        migrate_roles_and_users(conn)

        with conn.cursor() as cur:
            # 2. Migrate production_reports columns
            if not table_exists(cur, "production_reports"):
                print("Table 'production_reports' does not exist.")
                print("Run the app once to create the base schema, then rerun this migration.")
                return

            missing = []
            columns = {
                "acetate_type":       "VARCHAR(100) DEFAULT ''",
                "acetate_batch":      "VARCHAR(100) DEFAULT 'No Batch'",
                "paper_type":         "VARCHAR(100) DEFAULT ''",
                "paper_batch":        "VARCHAR(100) DEFAULT 'No Batch'",
                "pva_glue_type":      "VARCHAR(100) DEFAULT ''",
                "pva_batch":          "VARCHAR(100) DEFAULT 'No Batch'",
                "hm_glue_type":       "VARCHAR(100) DEFAULT ''",
                "hm_batch":           "VARCHAR(100) DEFAULT 'No Batch'",
                "triacetin_type":     "VARCHAR(100) DEFAULT ''",
                "tri_batch":          "VARCHAR(100) DEFAULT 'No Batch'",
                "shift_time_range":   "VARCHAR(255) DEFAULT ''",
                "box_type":           "INTEGER DEFAULT 0",
                "diameter":           "DOUBLE PRECISION DEFAULT 0.0",
                "length":             "DOUBLE PRECISION DEFAULT 0.0",
                "pd":                 "INTEGER DEFAULT 0",
                "weight":             "DOUBLE PRECISION DEFAULT 0.0",
                "lot_number":         "VARCHAR(255) DEFAULT ''",
                "machine_counter":    "INTEGER DEFAULT 0",
                "produced_rods":      "INTEGER DEFAULT 0",
                "machine_efficiency": "DOUBLE PRECISION DEFAULT 0.0",
                "difference":         "DOUBLE PRECISION DEFAULT 0.0",
                "diff_percent":       "VARCHAR(255) DEFAULT '0%'",
                "efficiency_box_min": "DOUBLE PRECISION DEFAULT 0.0",
                "total_acetate":      "DOUBLE PRECISION DEFAULT 0.0",
                "total_paper":        "DOUBLE PRECISION DEFAULT 0.0",
                "total_pva":          "DOUBLE PRECISION DEFAULT 0.0",
                "total_hm":           "DOUBLE PRECISION DEFAULT 0.0",
                "total_triacetin":    "DOUBLE PRECISION DEFAULT 0.0",
                "remarks":            "VARCHAR(255) DEFAULT ''",
                "is_modified_manually": "BOOLEAN DEFAULT FALSE",
                "materials_json":     "TEXT",
                "sync_at":            "TIMESTAMP DEFAULT now()",
                "status":             "VARCHAR(20) DEFAULT 'original'",
                "parent_report_id":   "INTEGER",
                "edited_by":          "VARCHAR(50)",
                "edited_at":          "TIMESTAMP",
                "timezone_offset":    "INTEGER",
                "submitted_at_utc":   "TIMESTAMP",
                "is_archived":        "BOOLEAN DEFAULT FALSE",
                "is_deleted":         "BOOLEAN DEFAULT FALSE",
                "deleted_by":         "VARCHAR(50)",
                "deleted_at":         "TIMESTAMP",
            }

            existing = []
            for name in columns.keys():
                if column_exists(cur, "production_reports", name):
                    existing.append(name)
                else:
                    print(f"Adding missing column {name}")
                    add_column(cur, "production_reports", f"{name} {columns[name]}")
                    missing.append(name)

            print(f"Existing columns: {existing}")
            if missing:
                print("Migration finished. Added:", missing)
            else:
                print("Migration finished. No changes needed.")

            # 3. Migrate purchase_orders columns
            if not table_exists(cur, "purchase_orders"):
                print("i  [Migrate] 'purchase_orders' table not found -- skipping.")
            else:
                po_columns = {
                    "is_archived": "BOOLEAN DEFAULT FALSE",
                }
                po_missing = []
                for col, definition in po_columns.items():
                    if not column_exists(cur, "purchase_orders", col):
                        cur.execute(f"ALTER TABLE purchase_orders ADD COLUMN {col} {definition}")
                        po_missing.append(col)
                        print(f"ok [Migrate] Added purchase_orders.{col}")
                if po_missing:
                    print(f"ok [Migrate] purchase_orders new columns: {po_missing}")
                else:
                    print("i  [Migrate] purchase_orders already up to date.")

    conn.commit()

if __name__ == "__main__":
    main()
