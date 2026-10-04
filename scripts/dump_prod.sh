#!/usr/bin/env bash
# Dump the LIVE production database into prod_backup.sql (plain SQL).
# RUN THIS INSIDE WSL ON THE REMOTE PRODUCTION SERVER, not locally.
#
# Replace <DB_USER> and <DB_PASSWORD> with the real production credentials,
# and 127.0.0.1:5432 with the host/port the production Postgres listens on.
# If Postgres uses a local socket, drop -h 127.0.0.1 -p 5432.

set -euo pipefail

DB_USER="<DB_USER>"
DB_PASSWORD="<DB_PASSWORD>"
DB_HOST="127.0.0.1"
DB_PORT="5432"
DB_NAME="production_log_dev"

PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-privileges -f prod_backup.sql

echo "==> Done. Dump written to prod_backup.sql"