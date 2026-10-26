# ============================================================================
# Install the MES backend as a Windows service (Scheduled Task) in $TargetDir.
#
# This is the "installer": it copies the project from the development folder
# (the folder that contains this scripts/ dir) to $TargetDir, creates a fresh
# Python virtual environment, installs the backend dependencies, registers a
# boot-time Scheduled Task that runs uvicorn as SYSTEM (hidden, output routed
# to logs\server.log), and starts it.
#
# Usage (run from an ELEVATED PowerShell in the development folder,
#        e.g. Documents\Python\mes_pft):
#   powershell -ExecutionPolicy Bypass -File scripts\install_server.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_server.ps1 -Port 8001
#   powershell -ExecutionPolicy Bypass -File scripts\install_server.ps1 -RunMigrations
#   powershell -ExecutionPolicy Bypass -File scripts\install_server.ps1 `
#       -Python "C:\Python312\python.exe"
# ============================================================================

param(
    [string]$TargetDir = "C:\MES_System",
    [string]$TaskName  = "MES_Server",
    [int]   $Port      = 8000,
    [string]$Python    = "python",
    [switch]$RunMigrations
)

$ErrorActionPreference = 'Stop'
$Source = Split-Path -Parent $PSScriptRoot   # the development folder (mes_pft/)

# --- elevation guard (registering/starting a SYSTEM task requires admin) ------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "This script must be run from an elevated PowerShell (Run as Administrator)."
}

# --- sanity checks -----------------------------------------------------------
if ($Source.TrimEnd('\') -ieq $TargetDir.TrimEnd('\')) {
    throw "Source folder and target folder are the same ($Source). Run this from the development folder, not from $TargetDir."
}
if (-not (Test-Path (Join-Path $Source 'backend\app\main.py'))) {
    throw "backend\app\main.py not found under $Source - is this the mes_pft root?"
}
if (-not (Test-Path (Join-Path $Source 'backend\requirements.txt'))) {
    throw "backend\requirements.txt not found under $Source."
}

# --- 0. Stop any existing deployment (keeps re-install safe) ------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "==> Stopping existing Scheduled Task '$TaskName' ..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# --- 1. Copy the project (excluding junk / secrets / generated artefacts) -----
# Directories are matched by name at any depth; files by name/pattern.
$excludeDirs = @('.git', '.venv', 'venv', '__pycache__', '.dart_tool', '.idea', '.vscode',
                 'logs', 'pdf_archive', 'apk_releases', 'backups', 'build', '.gradle', '.kotlin')
$excludeFiles = @('*.pyc', '*.log', '*_log_backup', '*.db', '*.db-wal', '*.db-shm', '*.dump',
                  'token.json', '*.jks', '*.keystore', 'credentials.json', 'Gdrive_secret.json',
                  '.env', '.env.test', '.env.disabled', '*.spec')

Write-Host "==> Copying $Source -> $TargetDir ..."
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$robocopyArgs = @($Source, $TargetDir, '/E', '/R:2', '/W:3', '/NFL', '/NDL', '/NP', '/XD') `
              + $excludeDirs + @('/XF') + $excludeFiles
& robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

# Explicitly ship the Flutter web console. frontend\build\web is a 'build'
# artefact (excluded above) but the backend serves it at '/'.
$webBuild = Join-Path $Source 'frontend\build\web'
if (Test-Path $webBuild) {
    Write-Host '==> Copying frontend web build (frontend\build\web) ...'
    & robocopy $webBuild (Join-Path $TargetDir 'frontend\build\web') /E /R:2 /W:3 /NFL /NDL /NP
    if ($LASTEXITCODE -ge 8) { throw "robocopy (web build) failed with exit code $LASTEXITCODE" }
}

# --- 2. Seed .env (never overwrite an existing production .env) ---------------
$targetEnv = Join-Path $TargetDir '.env'
if (-not (Test-Path $targetEnv)) {
    $sourceEnv = Join-Path $Source '.env'
    if (Test-Path $sourceEnv) {
        Copy-Item $sourceEnv $targetEnv -Force
        Write-Host '==> Copied .env from source. Review production values before going live.'
    } else {
        Copy-Item (Join-Path $Source '.env.example') $targetEnv -Force
        Write-Host '==> Created .env from .env.example. EDIT the production values before first start!'
    }
} else {
    Write-Host "==> Existing .env found at $targetEnv - left untouched."
}

# --- 3. Fresh Python virtual environment --------------------------------------
$venvDir = Join-Path $TargetDir 'venv'
if (Test-Path $venvDir) {
    Write-Host "==> Removing existing venv at $venvDir ..."
    Remove-Item -Path $venvDir -Recurse -Force
}
Write-Host '==> Creating virtual environment ...'
& $Python -m venv $venvDir
if ($LASTEXITCODE -ne 0) { throw "python -m venv failed (Python used: $Python)" }
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

# --- 4. Install dependencies --------------------------------------------------
Write-Host '==> Installing backend dependencies ...'
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip install --upgrade pip failed' }
& $venvPython -m pip install -r (Join-Path $TargetDir 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install -r requirements.txt failed' }

# --- 5. Optional: apply Alembic migrations ------------------------------------
if ($RunMigrations) {
    Write-Host '==> Applying Alembic migrations (alembic upgrade head) ...'
    Push-Location (Join-Path $TargetDir 'backend')
    try {
        & (Join-Path $TargetDir 'venv\Scripts\alembic.exe') upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head failed' }
    } finally {
        Pop-Location
    }
}

# --- 6. Launcher + log directory ----------------------------------------------
$logDir = Join-Path $TargetDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$launcher   = Join-Path $TargetDir 'run_server.cmd'
$logFile    = Join-Path $logDir 'server.log'
$backendDir = Join-Path $TargetDir 'backend'
$launcherContent = @"
@echo off
rem MES backend launcher (run by the '$TaskName' Scheduled Task as SYSTEM).
rem Output is appended to $logFile
cd /d "$backendDir"
"$venvPython" -m uvicorn app.main:app --host 0.0.0.0 --port $Port >> "$logFile" 2>&1
"@
[System.IO.File]::WriteAllText($launcher, $launcherContent, [System.Text.Encoding]::ASCII)
Write-Host "==> Wrote launcher: $launcher"

# --- 7. Register + start the Scheduled Task -----------------------------------
Write-Host "==> Registering Scheduled Task '$TaskName' (SYSTEM, runs at startup, hidden) ..."
$action   = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c `"$launcher`"" -WorkingDirectory $TargetDir
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
Write-Host "==> Starting '$TaskName' ..."
Start-ScheduledTask -TaskName $TaskName

Write-Host ''
Write-Host 'Install complete.'
Write-Host "  Target:  $TargetDir"
Write-Host "  Service: Scheduled Task '$TaskName' (SYSTEM, auto-start, hidden)"
Write-Host "  Log:     $logFile"
Write-Host "  URL:     http://localhost:$Port"

