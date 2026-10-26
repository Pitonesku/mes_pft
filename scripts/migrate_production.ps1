# ============================================================================
# One-shot PRODUCTION migration: move the old production_log relational data
# plus the Data_Bridge quality measurements into a fresh MES database on the
# Windows PostgreSQL (PostgreSQL_For_Odoo / Postgres 12).
#
# Order of operations (mirrors run_migration.ps1, but targets production):
#   1. Stop the MES_Server Scheduled Task.
#   2. Create the target database (drop+recreate with -Force).
#   3. Restore the dump (-Fc archive via pg_restore, or plain SQL via psql).
#   4. Run `alembic upgrade head` + the ETL backfill from measurements.db,
#      pointed at the target DB via a temporary .env swap.
#   5. Reassign ownership to the app role (skipped when DbUser == AppUser).
#   6. Print verification row counts.
#
# The app itself is NOT restarted here: finish by editing C:\MES_System\.env
# (DB_NAME, ENV=production, SECRET_KEY, ...) and then Start-ScheduledTask.
#
# Usage (elevated PowerShell, from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\migrate_production.ps1 `
#       -Dump production_log_fresh.sql -Force
# ============================================================================

param(
    [string]$Dump       = 'production_log_fresh.sql',   # -Fc archive or plain-SQL dump
    [string]$Sqlite     = 'C:\Data_Bridge V.2.0\measurements.db',
    [string]$TargetDir  = 'C:\MES_System',
    [string]$TaskName   = 'MES_Server',
    [string]$DbHost     = '127.0.0.1',
    [int]   $DbPort     = 5432,
    [string]$DbUser     = 'openpg',          # superuser role for create/restore/migrate
    [string]$DbPassword = '',                 # prompts if empty
    [string]$DbName     = 'mes_production',
    [string]$AppUser    = 'openpg',           # role the MES app uses (gets ownership)
    [string]$PsqlBin    = '',                 # optional path to the Postgres bin dir
    [switch]$Force                            # drop + recreate $DbName if it exists
)

$ErrorActionPreference = 'Stop'

# --- elevation guard ---------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw 'This script must be run from an elevated PowerShell (Run as Administrator).'
}

# --- locate psql.exe (PostgreSQL_For_Odoo is bundled under Odoo, not PG) ------
function Find-PgTool([string]$Name) {
    if ($PsqlBin -and (Test-Path (Join-Path $PsqlBin $Name))) { return (Join-Path $PsqlBin $Name) }
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($svc in (Get-CimInstance Win32_Service -Filter "Name LIKE '%postgres%'" -ErrorAction SilentlyContinue)) {
        if ($svc.PathName -match '"([^"]*pg_ctl\.exe)"') {
            $cand = Join-Path (Split-Path -Parent $Matches[1]) $Name
            if (Test-Path $cand) { return $cand }
        }
    }
    foreach ($v in @('18','17','16','15','14','13','12','11','10')) {
        $p = "C:\Program Files\PostgreSQL\$v\bin\$Name"
        if (Test-Path $p) { return $p }
    }
    throw "Could not find $Name. Pass -PsqlBin."
}
$psql = Find-PgTool 'psql.exe'
$pg_restore = Find-PgTool 'pg_restore.exe'
Write-Host "psql: $psql"
Write-Host "pg_restore: $pg_restore"

# --- resolve password ---------------------------------------------------------
if (-not $DbPassword) {
    $sec = Read-Host "Postgres password for role '$DbUser'" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { $DbPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
$env:PGPASSWORD = $DbPassword
$env:PGCLIENTENCODING = 'UTF8'   # psql reads the plain-SQL dump as UTF-8 (Cyrillic-safe)

# --- sanity checks -----------------------------------------------------------
if (-not (Test-Path $Dump)) { throw "Dump not found: $Dump (run from the repo root)" }
if (-not (Test-Path $Sqlite)) { throw "SQLite measurements not found: $Sqlite" }
$venvPython = Join-Path $TargetDir 'venv\Scripts\python.exe'
$alembic    = Join-Path $TargetDir 'venv\Scripts\alembic.exe'
$backendDir = Join-Path $TargetDir 'backend'
foreach ($p in @($venvPython, $alembic, $backendDir)) {
    if (-not (Test-Path $p)) { throw "Missing in $TargetDir : $p (run install_server.ps1 first)" }
}

# --- 0. stop the MES service --------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "==> Stopping Scheduled Task '$TaskName' ..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
} else {
    Write-Host "==> Scheduled Task '$TaskName' not found - skipping stop."
}

# --- 1. create the target database -------------------------------------------
Write-Host "==> Checking reachability of ${DbHost}:${DbPort} as '$DbUser' ..."
$exists = & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'"
if ($LASTEXITCODE -ne 0) { throw "Cannot connect to Postgres at ${DbHost}:${DbPort} as '$DbUser'." }
if ("$exists".Trim() -eq '1') {
    if (-not $Force) { throw "Database '$DbName' already exists. Re-run with -Force to drop and recreate it." }
    Write-Host "==> Dropping existing database '$DbName' ..."
    & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DbName' AND pid <> pg_backend_pid()" 2>$null | Out-Null
    & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "DROP DATABASE $DbName"
    if ($LASTEXITCODE -ne 0) { throw 'DROP DATABASE failed (is another client connected?)' }
}
Write-Host "==> Creating database '$DbName' ..."
& $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "CREATE DATABASE $DbName"
if ($LASTEXITCODE -ne 0) { throw 'CREATE DATABASE failed' }

# --- 2. restore the dump (auto-detect -Fc custom archive vs plain SQL) --------
$magic = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes((Resolve-Path $Dump).Path)[0..4])
if ($magic -eq 'PGDMP') {
    Write-Host "==> Restoring custom-format archive $Dump into $DbName (pg_restore) ..."
    & $pg_restore -h $DbHost -p $DbPort -U $DbUser -d $DbName --no-owner --no-privileges --exit-on-error $Dump
    if ($LASTEXITCODE -ne 0) { throw "pg_restore of $Dump failed (see output above)" }
} else {
    Write-Host "==> Restoring plain-SQL $Dump into $DbName (psql, ON_ERROR_STOP) ..."
    & $psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $Dump
    if ($LASTEXITCODE -ne 0) { throw "restore of $Dump failed (see output above)" }
}

# --- 3. alembic upgrade head + ETL backfill (temp .env points at $DbName) ----
$envPath = Join-Path $TargetDir '.env'
if (-not (Test-Path $envPath)) { throw "No .env found at $envPath" }
$envBackup = "$envPath.pre_migration"
Copy-Item $envPath $envBackup -Force
$tempEnv = "DB_USER=$DbUser`nDB_PASSWORD=$DbPassword`nDB_HOST=$DbHost`nDB_PORT=$DbPort`nDB_NAME=$DbName`nENV=development`nMES_PLANT_TIMEZONE=Europe/Budapest`n"
try {
    # No-BOM UTF-8 so the first key (DB_USER) is not prefixed with a BOM.
    [System.IO.File]::WriteAllText($envPath, $tempEnv, (New-Object System.Text.UTF8Encoding($false)))

    Push-Location $backendDir
    try {
        Write-Host '==> Running alembic upgrade head ...'
        & $alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head failed' }

        Write-Host "==> Running ETL backfill from $Sqlite ..."
        & $venvPython -m app.scripts.etl_backfill $Sqlite
        if ($LASTEXITCODE -ne 0) { throw 'ETL backfill failed' }
    } finally {
        Pop-Location
    }
} finally {
    # Always restore the original .env, even on failure.
    Copy-Item $envBackup $envPath -Force
    Remove-Item $envBackup -ErrorAction SilentlyContinue
}

# --- 4. reassign ownership to the app role (skipped when DbUser == AppUser) ---
if ($DbUser -ne $AppUser) {
    Write-Host "==> Granting ownership of '$DbName' to app role '$AppUser' ..."
    & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "ALTER DATABASE $DbName OWNER TO $AppUser;"
    if ($LASTEXITCODE -ne 0) { throw "ALTER DATABASE OWNER failed (does role '$AppUser' exist?)" }
    & $psql -h $DbHost -p $DbPort -U $DbUser -d $DbName -c "ALTER SCHEMA public OWNER TO $AppUser; REASSIGN OWNED BY $DbUser TO $AppUser;"
    if ($LASTEXITCODE -ne 0) { throw 'grant/REASSIGN failed' }
} else {
    Write-Host "==> DbUser equals AppUser ('$DbUser') - all objects already owned by the app role."
}

# --- 5. verification counts (non-fatal) --------------------------------------
Write-Host '==> Verification counts:'
& $psql -X -P pager=off -h $DbHost -p $DbPort -U $DbUser -d $DbName -c "SELECT 'material_dictionary' t, count(*) FROM material_dictionary UNION ALL SELECT 'purchase_orders', count(*) FROM purchase_orders UNION ALL SELECT 'users', count(*) FROM users UNION ALL SELECT 'machines', count(*) FROM machines UNION ALL SELECT 'shift_sessions', count(*) FROM shift_sessions UNION ALL SELECT 'production_runs', count(*) FROM production_runs UNION ALL SELECT 'quality_samples', count(*) FROM quality_samples UNION ALL SELECT 'quality_measurements', count(*) FROM quality_measurements;"

Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "Migration complete into '$DbName'."
Write-Host ''
Write-Host 'NEXT STEPS (manual):'
Write-Host "  1. Edit $envPath -> DB_NAME=$DbName, DB_USER=$AppUser, ENV=production,"
Write-Host '     a real SECRET_KEY, and production ADMIN_* values.'
Write-Host "  2. Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  3. Watch $TargetDir\logs\server.log for a clean startup."

