"""
LEGACY / FROZEN — do not extend.

This module predates the Alembic migrations and the current ``roles`` schema
(it still uses a ``name`` column instead of ``role_name``), so it is NOT run
automatically and is only kept for historical reference. New schema goes through
Alembic (000N migrations); do not add runtime DDL here.

The superadmin seed below now bcrypt-hashes its password (previously it stored
the plain-text ``123``). Password verification is bcrypt-only (see
``app/password_utils.py``).
"""

import os
import pathlib
import importlib
import psycopg2
import bcrypt

# ---------------------------------------------------------------------------
# Load .env via the shared helper (searches repo root, backend/, then app/).
# ---------------------------------------------------------------------------
if __package__:
    config = importlib.import_module(f"{__package__}.config")
else:
    import config

ENV_PATH = config.load_env()
print(f"[InitDB] Loaded .env from: {ENV_PATH}")

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

def get_conn():
    """Create a psycopg2 connection using env credentials."""
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )


def init_db():
    """FROZEN — refused to run. Schema is managed by Alembic migrations only."""
    raise RuntimeError(
        "init_db.py is FROZEN and refuses to run: schema is managed by Alembic "
        "migrations only. Use `alembic upgrade head` instead."
    )
    # --- legacy code below is unreachable and kept only for historical reference ---
    try:
        conn = get_conn()
        cursor = conn.cursor()
        print(f"--- Подключение к PostgreSQL: {DB_NAME} ---")

        # 1. ПЕРЕСОЗДАЕМ ТАБЛИЦУ РОЛЕЙ
        cursor.execute("DROP TABLE IF EXISTS roles CASCADE")
        cursor.execute('''
            CREATE TABLE roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL
            )
        ''')
        
        roles = [(1, 'superAdmin'), (2, 'manager'), (3, 'operator')]
        for role_id, role_name in roles:
            cursor.execute(
                "INSERT INTO roles (id, name) VALUES (%s, %s)",
                (role_id, role_name)
            )
        print("✅ Таблица ролей пересоздана и заполнена.")

        # 2. ПРОВЕРЯЕМ/СОЗДАЕМ ТАБЛИЦУ ПОЛЬЗОВАТЕЛЕЙ
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email VARCHAR(255),
                role_id INTEGER REFERENCES roles(id)
            )
        ''')

        # 3. ДОБАВЛЯЕМ СУПЕРАДМИНА
        cursor.execute("SELECT id FROM users WHERE username = %s", ("superadmin",))
        if not cursor.fetchone():
            superadmin_hash = bcrypt.hashpw(b"123", bcrypt.gensalt()).decode("utf-8")
            cursor.execute('''
                INSERT INTO users (username, password_hash, email, role_id)
                VALUES (%s, %s, %s, %s)
            ''', ("superadmin", superadmin_hash, "admin@factory.com", 1))
            print("✅ Юзер 'superadmin' успешно добавлен.")
        else:
            print("ℹ️ 'superadmin' уже существует.")

        conn.commit()
        cursor.close()
        conn.close()
        print("--- Инициализация завершена успешно ---")

    except Exception as e:
        print(f"❌ Ошибка: {e}")


def ensure_ai_user():
    """
    Create (if not exists) a read-only PostgreSQL user for the AI Text-to-SQL agent.
    Grants SELECT-only permissions on all tables in the public schema.
    
    Reads AI_DB_USER and AI_DB_PASSWORD from .env.
    Idempotent — safe to run on every server startup.
    """
    ai_user = os.getenv("AI_DB_USER")
    ai_password = os.getenv("AI_DB_PASSWORD")

    if not ai_user or not ai_password:
        print("⚠️  [InitDB] AI_DB_USER or AI_DB_PASSWORD not set — skipping AI read-only user creation.")
        return

    try:
        conn = get_conn()
        conn.autocommit = True  # CREATE USER must run outside a transaction
        cursor = conn.cursor()

        # Check if the user already exists
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ai_user,))
        if cursor.fetchone():
            print(f"i  [InitDB] PostgreSQL role '{ai_user}' already exists — skipping creation.")
        else:
            # Use parameterized query to avoid SQL injection
            cursor.execute(
                f'CREATE USER "{ai_user}" WITH PASSWORD %s',
                (ai_password,),
            )
            print(f"✅ [InitDB] PostgreSQL role '{ai_user}' created.")

        # Grant permissions (idempotent — safe to run repeatedly)
        cursor.execute(f'GRANT CONNECT ON DATABASE "{DB_NAME}" TO "{ai_user}"')
        cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{ai_user}"')
        cursor.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{ai_user}"')
        cursor.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "{ai_user}"'
        )
        print(f"✅ [InitDB] Read-only permissions granted to '{ai_user}' on database '{DB_NAME}'.")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ [InitDB] Failed to create AI read-only user: {e}")
        # Do NOT raise — this is a non-critical setup step


if __name__ == "__main__":
    init_db()