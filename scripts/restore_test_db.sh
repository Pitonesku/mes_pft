#!/usr/bin/env bash
# Restore the custom-format production dump (production_log_db_dump) into the
# LOCAL test PostgreSQL container (mes_db_test, host port 5433).
# The dump is pg_dump -Fc (custom format), so pg_restore is used (NOT psql).
#
# Usage:  bash scripts/restore_test_db.sh [path/to/dump]
# Requires: docker compose --profile test up -d db_test

set -euo pipefail

DUMP="${1:-production_log_db_dump}"
if [[ ! -f "$DUMP" ]]; then
  echo "ERROR: dump file not found: $DUMP" >&2
  exit 1
fi

echo "==> Copying $DUMP into mes_db_test ..."
docker cp "$DUMP" mes_db_test:/tmp/prod_dump.dump

echo "==> Restoring into mes_test_db (pg_restore, --no-owner --no-privileges) ..."
docker exec mes_db_test pg_restore -U postgres -d mes_test_db \
  --no-owner --no-privileges --clean --if-exists /tmp/prod_dump.dump

echo "==> Done. Test DB restored."