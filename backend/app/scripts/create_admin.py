"""
One-off script to create the admin role and admin user for the SQLAdmin panel.
Run from the project root:
    python create_admin.py

Reads DB credentials and admin settings from a .env file in the SAME folder as this script.

Required .env variables:
    DB_USER          – PostgreSQL username (e.g. postgres)
    DB_PASSWORD      – PostgreSQL password
    DB_HOST          – PostgreSQL host (e.g. 127.0.0.1)
    DB_PORT          – PostgreSQL port (e.g. 5432)
    DB_NAME          – Database name (e.g. production_log_dev)

Optional (defaults shown):
    ADMIN_USERNAME=admin
    ADMIN_PASSWORD=admin
    ADMIN_EMAIL=admin@factory.local
"""
import os
import sys
import pathlib
import bcrypt
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Locate and load .env. create_admin.py lives in app/scripts/, so search the
# repo root, then backend/, then the scripts folder.
# ---------------------------------------------------------------------------
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent          # app/scripts/
BACKEND_DIR = SCRIPT_DIR.parent.parent                        # backend/
_candidates = [BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env", SCRIPT_DIR / ".env"]
ENV_PATH = next((c for c in _candidates if c.is_file()), None)

if ENV_PATH is None:
    print("ERROR: .env file not found (searched repo root, backend/, scripts/).")
    print("Create a .env file with your PostgreSQL credentials and re-run.")
    sys.exit(1)

print(f"Loading .env from: {ENV_PATH}")
load_dotenv(dotenv_path=str(ENV_PATH), override=True)

# ---------------------------------------------------------------------------
# Read required DB credentials
# ---------------------------------------------------------------------------
def _check_env(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise RuntimeError(f"{var} is not set in .env (file: {ENV_PATH})")
    return value

DB_USER = _check_env("DB_USER")
DB_PASSWORD = _check_env("DB_PASSWORD")
DB_HOST = _check_env("DB_HOST")
DB_PORT = _check_env("DB_PORT")
DB_NAME = _check_env("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
_masked_user = DB_USER[:2] + "***" if len(DB_USER) > 2 else "***"
print(f"Connecting to: postgresql://{_masked_user}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    # -----------------------------------------------------------------------
    # 1. Check current state
    # -----------------------------------------------------------------------
    role_count = session.execute(text("SELECT COUNT(*) FROM roles")).scalar()
    user_count = session.execute(text("SELECT COUNT(*) FROM users")).scalar()
    print(f"Current state: {role_count} role(s), {user_count} user(s)")

    # -----------------------------------------------------------------------
    # 2. Create admin role if it doesn't exist
    # -----------------------------------------------------------------------
    admin_role = session.execute(
        text("SELECT id FROM roles WHERE LOWER(role_name) = 'admin'")
    ).fetchone()

    if admin_role:
        admin_role_id = admin_role[0]
        print(f"Admin role already exists (id={admin_role_id}) — skipping role creation.")
    else:
        session.execute(
            text(
                """
                INSERT INTO roles (
                    role_name,
                    can_create_po, can_edit_po, can_edit_report,
                    can_manage_users, can_setup_machines, can_view_all_reports
                ) VALUES (
                    'admin',
                    TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
                )
                """
            )
        )
        session.flush()
        admin_role_id = session.execute(
            text("SELECT id FROM roles WHERE role_name = 'admin'")
        ).scalar()
        print(f"Admin role created (id={admin_role_id}, all permissions granted).")

    # -----------------------------------------------------------------------
    # 3. Create admin user (or reset password if already exists)
    # -----------------------------------------------------------------------
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin")
    email = os.getenv("ADMIN_EMAIL", "admin@factory.local")

    if username == "admin" and password == "admin":
        print(
            "!! WARNING: using DEFAULT credentials (admin / admin). "
            "Set ADMIN_USERNAME and ADMIN_PASSWORD in .env for production!"
        )

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    existing_user = session.execute(
        text("SELECT id FROM users WHERE username = :u"), {"u": username}
    ).fetchone()

    if existing_user:
        user_id = existing_user[0]
        session.execute(
            text(
                """
                UPDATE users
                SET password_hash = :ph, role_id = :rid, email = :e, is_inactive = FALSE
                WHERE id = :uid
                """
            ),
            {"ph": password_hash, "rid": admin_role_id, "e": email, "uid": user_id},
        )
        print(f"User '{username}' already exists (id={user_id}) — password RESET and role updated.")
    else:
        session.execute(
            text(
                """
                INSERT INTO users (username, email, password_hash, role_id, is_inactive)
                VALUES (:u, :e, :ph, :rid, FALSE)
                """
            ),
            {
                "u": username,
                "e": email,
                "ph": password_hash,
                "rid": admin_role_id,
            },
        )
        session.flush()
        new_id = session.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": username}
        ).scalar()
        print(f"Admin user '{username}' created (id={new_id}).")

    session.commit()

    print()
    print("=" * 60)
    print("  Admin user is ready!")
    print(f"  Username : {username}")
    print(f"  Password : {password}")
    print(f"  Login at : http://localhost:8000/admin")
    print("=" * 60)

except Exception as e:
    session.rollback()
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    session.close()