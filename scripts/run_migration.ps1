# ============================================================================
# Full test pipeline: restore the production dump into an ISOLATED test DB,
# run the Alembic migration, and backfill the unified quality tables from
# measurements.db.
#
# The target Postgres can be the Docker test container OR any reachable server
# (e.g. a native PostgreSQL 18 install). Docker is NOT required for the restore
# itself; you just need a running Postgres + the credentials below.
#
# Defaults match the `db_test` service in docker-compose.yml (port 5433).
#
# Usage (Docker test DB):
#   docker compose --profile test up -d db_test
#   powershell -ExecutionPolicy Bypass -File scripts\run_migration.ps1
#
# Usage (native PostgreSQL 18 on 5432, adjust credentials):
#   powershell -ExecutionPolicy Bypass -File scripts\run_migration.ps1 `
#     -DbHost 127.0.0.1 -DbPort 5432 -DbUser postgres -DbPassword <pw> `
#     -DbName mes_test_db
# ============================================================================

param(
    [string]$Dump       = 'production_log_db_dump',
    [string]$Sqlite     = 'measurements.db',
    [string]$DbHost     = '127.0.0.1',
    [int]   $DbPort     = 5433,
    [string]$DbUser     = 'postgres',
    [string]$DbPassword = 'test_password',
    [string]$DbName     = 'mes_test_db',
    [string]$PgBin      = ''   # optional: path to PostgreSQL bin (pg_restore/psql)
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot   # mes_pft/
Set-Location $root

# --- 1. Locate pg_restore / psql -------------------------------------------
function Find-PgTool([string]$Name) {
    if ($PgBin -and (Test-Path (Join-Path $PgBin $Name))) { return (Join-Path $PgBin $Name) }
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($v in @('18', '17', '16', '15', '14')) {
        $p = "C:\Program Files\PostgreSQL\$v\bin\$Name"
        if (Test-Path $p) { return $p }
    }
    throw "Could not find $Name. Install PostgreSQL tools or pass -PgBin."
}
$pg_restore = Find-PgTool 'pg_restore.exe'
$psql       = Find-PgTool 'psql.exe'
Write-Host "pg_restore: $pg_restore"
Write-Host "psql      : $psql"

$env:PGPASSWORD = $DbPassword

# --- 2. (Re)create the test DB from scratch (clean slate) --------------------
Write-Host "==> Checking reachability of ${DbHost}:${DbPort} as '$DbUser' ..."
& $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -tAc "SELECT 1" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Cannot reach Postgres at ${DbHost}:${DbPort} as '$DbUser'. Check credentials / that the server is running."
}

Write-Host "==> Dropping & recreating database $DbName (clean slate) ..."
& $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DbName' AND pid <> pg_backend_pid()" 2>$null | Out-Null
& $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "DROP DATABASE IF EXISTS \"$DbName\""
if ($LASTEXITCODE -ne 0) { throw 'DROP DATABASE failed (is another client connected?)' }
& $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "CREATE DATABASE \"$DbName\""
if ($LASTEXITCODE -ne 0) { throw 'CREATE DATABASE failed' }

# --- 3. Restore the custom-format dump -------------------------------------
if (-not (Test-Path $Dump)) { throw "Dump not found: $Dump (run from repo root)" }
Write-Host "==> Restoring $Dump into $DbName ..."
& $pg_restore -h $DbHost -p $DbPort -U $DbUser -d $DbName --no-owner --no-privileges --clean --if-exists $Dump
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }

# --- 4. Alembic + ETL (pointed at the test DB via a temp .env) -------------
$tmpEnv = Join-Path $root '.env'
if (Test-Path $tmpEnv) { throw "Refusing to overwrite existing repo-root .env at $tmpEnv" }
$envContent = "DB_USER=$DbUser`nDB_PASSWORD=$DbPassword`nDB_HOST=$DbHost`nDB_PORT=$DbPort`nDB_NAME=$DbName`n"

try {
    # No-BOM UTF-8 so the first key (DB_USER) is not prefixed with a BOM.
    [System.IO.File]::WriteAllText($tmpEnv, $envContent, (New-Object System.Text.UTF8Encoding($false)))

    Push-Location backend
    Write-Host '==> Running alembic upgrade head ...'
    & .\.venv\Scripts\alembic.exe upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }

    Write-Host '==> Running ETL backfill ...'
    & .\.venv\Scripts\python.exe -m app.scripts.etl_backfill (Join-Path $root $Sqlite)
    if ($LASTEXITCODE -ne 0) { throw 'ETL failed' }
    Pop-Location
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    Remove-Item $tmpEnv -ErrorAction SilentlyContinue
}

# --- 5. Report row counts ---------------------------------------------------
Write-Host '==> Verification counts:'
& $psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -c "SELECT 'shift_sessions' AS t, count(*) FROM shift_sessions UNION ALL SELECT 'production_runs', count(*) FROM production_runs UNION ALL SELECT 'machine_aliases', count(*) FROM machine_aliases UNION ALL SELECT 'quality_samples', count(*) FROM quality_samples UNION ALL SELECT 'quality_measurements', count(*) FROM quality_measurements;"

Write-Host '==> Done.'