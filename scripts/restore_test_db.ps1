# Restore prod_backup.sql into the LOCAL test PostgreSQL container (mes_db_test).
# Run LOCALLY on Windows PowerShell after copying prod_backup.sql from the server.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\restore_test_db.ps1 [-Dump prod_backup.sql]

param(
    [string]$Dump = 'prod_backup.sql'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Dump)) {
    throw "Dump file not found: $Dump"
}

Write-Host "==> Restoring $Dump into mes_db_test (postgres / mes_test_db on 5433) ..."
Get-Content $Dump -Raw | docker exec -i mes_db_test psql -U postgres -d mes_test_db
if ($LASTEXITCODE -ne 0) { throw 'psql restore failed' }

Write-Host '==> Done. Test DB restored.'