# Restore the custom-format production dump into the LOCAL test PostgreSQL container.
# The dump is pg_dump -Fc (custom format), so pg_restore is used (NOT psql).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\restore_test_db.ps1 [-Dump production_log_db_dump]
# Requires: docker compose --profile test up -d db_test

param(
    [string]$Dump = 'production_log_db_dump'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Dump)) { throw "Dump file not found: $Dump" }

Write-Host "==> Copying $Dump into mes_db_test ..."
docker cp $Dump mes_db_test:/tmp/prod_dump.dump
if ($LASTEXITCODE -ne 0) { throw 'docker cp failed' }

Write-Host '==> Restoring into mes_test_db (pg_restore, --no-owner --no-privileges) ...'
docker exec mes_db_test pg_restore -U postgres -d mes_test_db --no-owner --no-privileges --clean --if-exists /tmp/prod_dump.dump
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }

Write-Host '==> Done. Test DB restored.'