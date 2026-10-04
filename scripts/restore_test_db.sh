#!/usr/bin/env bash
# Restore prod_backup.sql into the LOCAL test PostgreSQL container (mes_db_test).
# Run LOCALLY after copying prod_backup.sql from the production server.
#
# Usage:  bash scripts/restore_test_db.sh [path/to/prod_backup.sql]
# Requires: the test DB is running (docker compose --profile test up -d db_test).

set -euo pipefail

DUMP="${1:-prod_backup.sql}"
if [[ ! -f "$DUMP" ]]; then
  echo "ERROR: dump file not found: $DUMP" >&2
  exit 1
fi

echo "==> Restoring $DUMP into mes_db_test (postgres / mes_test_db on 5433) ..."
docker exec -i mes_db_test psql -U postgres -d mes_test_db < "$DUMP"

echo "==> Done. Test DB restored."