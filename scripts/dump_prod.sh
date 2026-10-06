#!/usr/bin/env bash
# Dump the LIVE production database into a CUSTOM-format archive (pg_dump -Fc).
# This matches the format of `production_log_db_dump` and is restored with
# pg_restore (NOT psql). RUN THIS INSIDE WSL ON THE REMOTE PRODUCTION SERVER.
#
# Replace <DB_USER> and <DB_PASSWORD> with the real production credentials,
# and 127.0.0.1:5432 with the host/port the production Postgres listens on.

set -euo pipefail

DB_USER="<DB_USER>"
DB_PASSWORD="<DB_PASSWORD>"
DB_HOST="127.0.0.1"
DB_PORT="5432"
DB_NAME="production_log_dev"

OUT="${1:-production_log_db_dump}"

PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-privileges -Fc -f "$OUT"

echo "==> Done. Custom-format dump written to $OUT"