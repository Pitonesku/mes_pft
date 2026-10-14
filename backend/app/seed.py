"""
Database seeding for first-time startup.
Automatically creates the default admin role and admin user if the DB is empty.

Credentials are read from environment variables:
    ADMIN_USERNAME  (default: "admin")
    ADMIN_PASSWORD  (default: "admin")
    ADMIN_EMAIL     (default: "admin@factory.local")

Fully idempotent -- skipped when roles AND users tables both have rows.

IMPORTANT: All DB operations use raw SQL via SQLAlchemy text() so this function
works even on a legacy schema that has not yet had migrate_db.py run on it.
The migration (migrate_roles_and_users) runs first in main.py startup, so by the
time seed_initial_admin() is called the schema should already be correct.
"""

import os
import importlib
import bcrypt
from typing import Optional
from sqlalchemy import text

if __package__:
    database_mod = importlib.import_module(f"{__package__}.database")
    security_config = importlib.import_module(f"{__package__}.security_config")
    SessionLocal = database_mod.SessionLocal
else:
    import security_config
    from database import SessionLocal


def seed_initial_admin() -> None:
    """
    Seeds a default admin Role and User on the very first startup.

    - Checks row counts via raw SQL (safe against any column mismatch).
    - If roles > 0 AND users > 0  -> skip entirely.
    - If both are 0               -> insert admin role + admin user.
    - If roles > 0, users == 0    -> reuse existing admin role, insert user only.
    """
    db = SessionLocal()
    try:
        # -- 1. Count rows with raw SQL (schema-safe) --------------------------
        role_count = db.execute(text("SELECT COUNT(*) FROM roles")).scalar()
        user_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar()

        if role_count > 0 and user_count > 0:
            print("i  [Seed] Roles and users already exist -- skipping auto-seed.")
            return

        print("ok [Seed] Running first-startup seed...")

        admin_role_id = None

        # -- 2. Create the admin Role (if no roles exist) ----------------------
        if role_count == 0:
            db.execute(text("""
                INSERT INTO roles (
                    role_name,
                    can_create_po, can_edit_po, can_edit_report,
                    can_manage_users, can_setup_machines, can_view_all_reports
                ) VALUES (
                    'admin',
                    TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
                )
            """))
            db.flush()
            admin_role_id = db.execute(
                text("SELECT id FROM roles WHERE role_name = 'admin'")
            ).scalar()
            print(f"ok [Seed] Admin role created (id={admin_role_id}, all permissions granted).")
        else:
            # Roles exist but users do not -- find admin/superadmin role id
            row = db.execute(text(
                "SELECT id FROM roles WHERE LOWER(role_name) IN ('admin', 'superadmin') "
                "ORDER BY id LIMIT 1"
            )).fetchone()
            if row:
                admin_role_id = row[0]
            else:
                row = db.execute(text("SELECT id FROM roles ORDER BY id LIMIT 1")).fetchone()
                admin_role_id = row[0] if row else None
            print(f"i  [Seed] Roles already exist -- reusing role id={admin_role_id}.")

        # -- 3. Create the admin User (if no users exist) ----------------------
        if user_count == 0:
            if admin_role_id is None:
                print("err [Seed] Could not determine a role id -- skipping user creation.")
                db.rollback()
                return

            username = os.getenv("ADMIN_USERNAME", "admin")
            password = os.getenv("ADMIN_PASSWORD", "admin")
            email    = os.getenv("ADMIN_EMAIL",    "admin@factory.local")

            # Raises in production when the password is a default/placeholder.
            security_config.check_admin_seed_password(password)

            if username == "admin" and password == "admin":
                print(
                    "!! [Seed] WARNING: using DEFAULT credentials (admin / admin). "
                    "Set ADMIN_USERNAME and ADMIN_PASSWORD in .env before going to production!"
                )

            password_hash = bcrypt.hashpw(
                password.encode('utf-8'), bcrypt.gensalt()
            ).decode('utf-8')

            db.execute(text("""
                INSERT INTO users (username, email, password_hash, role_id, is_inactive)
                VALUES (:username, :email, :password_hash, :role_id, FALSE)
            """), {
                "username": username,
                "email":    email,
                "password_hash": password_hash,
                "role_id":  admin_role_id,
            })
            db.flush()
            new_id = db.execute(
                text("SELECT id FROM users WHERE username = :u"), {"u": username}
            ).scalar()
            print(f"ok [Seed] Admin user '{username}' created (id={new_id}, role_id={admin_role_id}).")
            print("ok [Seed] You can now log in at /admin with those credentials.")

        db.commit()
        print("ok [Seed] First-startup seed completed successfully.")

    except Exception as exc:
        db.rollback()
        print(f"err [Seed] Seeding failed: {exc}")
        raise
    finally:
        db.close()


# =============================================================================
# Telegram Bot Admin Auto-Seeding (runs every startup, idempotent)
# =============================================================================

def seed_telegram_admin() -> None:
    """
    Seeds the initial Telegram Bot admin user from environment variables.

    Reads INIT_ADMIN_TG_ID and INIT_ADMIN_USERNAME from .env.
    Runs on EVERY startup — idempotent by telegram_id uniqueness.

    If INIT_ADMIN_TG_ID is missing or invalid, logs a warning and returns safely.
    If the user already exists by telegram_id, skips silently.
    """
    from sqlalchemy import text

    tg_id_raw = os.getenv("INIT_ADMIN_TG_ID")
    if not tg_id_raw:
        print("⚠️  INIT_ADMIN_TG_ID is not set in .env. Auto-seeding skipped.")
        return

    try:
        # Take only the first whitespace-delimited token to handle inline comments
        # Example: "365768473 <-- комментарий" → 365768473
        tg_id = int(tg_id_raw.split()[0].strip())
    except (ValueError, TypeError):
        print(f"⚠️  INIT_ADMIN_TG_ID '{tg_id_raw}' is not a valid integer. Skipping.")
        return

    username = os.getenv("INIT_ADMIN_USERNAME", "admin")

    db = SessionLocal()
    try:
        # Check if a user with this telegram_id already exists
        existing = db.execute(
            text("SELECT id FROM users WHERE telegram_id = :tg_id"),
            {"tg_id": tg_id},
        ).fetchone()

        if existing:
            print(f"i  [Seed] Telegram admin with TG ID {tg_id} already exists (user id={existing[0]}) — skipping.")
            return

        # Insert the Telegram bot admin user with full permissions
        db.execute(
            text(
                """
                INSERT INTO users (username, email, password_hash, telegram_id, tg_role, can_use_ai, is_inactive)
                VALUES (:username, :email, :password, :tg_id, :tg_role, TRUE, FALSE)
                """
            ),
            {
                "username": username,
                "email": f"{username}@factory.local",
                "password": "",  # Bot users authenticate via Telegram ID, not password
                "tg_id": tg_id,
                "tg_role": "admin",
            },
        )
        db.commit()
        print("👑 Initial admin successfully added to the database!")
        print(f"   Username: {username}, Telegram ID: {tg_id}, Role: admin")

    except Exception as exc:
        db.rollback()
        print(f"err [Seed] Telegram admin seeding failed: {exc}")
        # Do NOT raise — seeding failure must not crash the server
    finally:
        db.close()


# =============================================================================
# Station ingest service account (runs every startup, idempotent)
# =============================================================================

def seed_station_ingest() -> Optional[int]:
    """Create the ``station_ingest`` service user if missing.

    The account has a locked password and no role/permissions; it exists only so
    a validated station API key can resolve to a real (low-privilege) user object.
    Returns the user id, or None on failure (never raises — seeding must not
    crash the server).
    """
    db = SessionLocal()
    try:
        existing = db.execute(
            text("SELECT id FROM users WHERE username = 'station_ingest'")
        ).fetchone()
        if existing:
            return existing[0]

        db.execute(text("""
            INSERT INTO users (username, email, password_hash, is_inactive)
            VALUES ('station_ingest', 'station_ingest@factory.local', :pw, FALSE)
        """), {"pw": "!locked"})
        db.commit()
        user_id = db.execute(
            text("SELECT id FROM users WHERE username = 'station_ingest'")
        ).scalar()
        print(f"ok [Seed] station_ingest service account created (id={user_id}).")
        return user_id
    except Exception as exc:
        db.rollback()
        print(f"err [Seed] station_ingest seeding failed: {exc}")
        return None
    finally:
        db.close()
