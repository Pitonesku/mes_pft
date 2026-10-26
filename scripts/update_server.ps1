# ============================================================================
# Update the deployed MES backend in $TargetDir from the current development
# folder, then restart the service.
#
# Stops the Scheduled Task, copies/overwrites the updated files (preserving the
# virtual environment, .env, database files, logs and generated artefacts so
# production data is never wiped), installs any new dependencies, optionally
# applies Alembic migrations (ON by default), and restarts the service.
#
# Usage (run from an ELEVATED PowerShell in the UPDATED development folder):
#   powershell -ExecutionPolicy Bypass -File scripts\update_server.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\update_server.ps1 -SkipMigrations
# ============================================================================

param(
    [string]$TargetDir = "C:\MES_System",
    [string]$TaskName  = "MES_Server",
    [switch]$SkipMigrations
)

$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $PSScriptRoot   # the updated development folder

# --- elevation guard (stopping/starting a SYSTEM task requires admin) ---------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "This script must be run from an elevated PowerShell (Run as Administrator)."
}

# --- sanity checks -----------------------------------------------------------
if ($Source.TrimEnd('\') -ieq $TargetDir.TrimEnd('\')) {
    throw "Source folder and target folder are the same ($Source). Run this from the updated development folder, not from $TargetDir."
}
if (-not (Test-Path (Join-Path $TargetDir 'backend\app\main.py'))) {
    throw "Target deployment not found at $TargetDir. Run install_server.ps1 first."
}
$venvPython = Join-Path $TargetDir 'venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at $venvPython. Run install_server.ps1 first."
}

# --- 1. Stop the running service ----------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "==> Stopping Scheduled Task '$TaskName' ..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
} else {
    Write-Host "==> Scheduled Task '$TaskName' not found - skipping stop."
}

# --- 2. Copy/overwrite updated files (never wipe venv / data / logs / .env) ---
# Directories are matched by name at any depth; files by name/pattern.
# '/E' (not '/MIR') overwrites and adds but never deletes target-only files.
$excludeDirs = @('.git', '.venv', 'venv', '__pycache__', '.dart_tool', '.idea', '.vscode',
                 'logs', 'pdf_archive', 'apk_releases', 'backups', 'build', '.gradle', '.kotlin')
$excludeFiles = @('*.pyc', '*.log', '*_log_backup', '*.db', '*.db-wal', '*.db-shm', '*.dump',
                  'token.json', '*.jks', '*.keystore', 'credentials.json', 'Gdrive_secret.json',
                  '.env', '.env.test', '.env.disabled', '*.spec')

Write-Host "==> Copying updated files $Source -> $TargetDir (preserving data) ..."
$robocopyArgs = @($Source, $TargetDir, '/E', '/R:2', '/W:3', '/NFL', '/NDL', '/NP', '/XD') `
              + $excludeDirs + @('/XF') + $excludeFiles
& robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

# Explicitly refresh the Flutter web console if a new build is present.
$webBuild = Join-Path $Source 'frontend\build\web'
if (Test-Path $webBuild) {
    Write-Host '==> Copying frontend web build (frontend\build\web) ...'
    & robocopy $webBuild (Join-Path $TargetDir 'frontend\build\web') /E /R:2 /W:3 /NFL /NDL /NP
    if ($LASTEXITCODE -ge 8) { throw "robocopy (web build) failed with exit code $LASTEXITCODE" }
}

# --- 3. Install any new dependencies ------------------------------------------
Write-Host '==> Installing dependencies (new/changed) ...'
& $venvPython -m pip install -r (Join-Path $TargetDir 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install -r requirements.txt failed' }

# --- 4. Apply Alembic migrations (on by default) ------------------------------
if (-not $SkipMigrations) {
    Write-Host '==> Applying Alembic migrations (alembic upgrade head) ...'
    Push-Location (Join-Path $TargetDir 'backend')
    try {
        & (Join-Path $TargetDir 'venv\Scripts\alembic.exe') upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head failed' }
    } finally {
        Pop-Location
    }
} else {
    Write-Host '==> Skipping Alembic migrations (-SkipMigrations).'
}

# --- 5. Restart the service ---------------------------------------------------
Write-Host "==> Starting '$TaskName' ..."
Start-ScheduledTask -TaskName $TaskName

Write-Host ''
Write-Host "Update complete. Service '$TaskName' restarted."
Write-Host "  Log: $(Join-Path $TargetDir 'logs\server.log')"
