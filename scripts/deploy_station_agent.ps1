# Deploy the station push agent as a silent background service on a station PC.
#
# Writes station_agent.ini next to the exe, then registers the exe to run at
# boot either as a Task Scheduler task (default if -UseTaskScheduler) or as an
# NSSM service.
#
# Examples:
#   NSSM (requires NSSM on PATH):
#     .\deploy_station_agent.ps1 -ExePath "C:\StationAgent\station_push_agent.exe" `
#       -WatchDir "C:\Station1\output" -MesBaseUrl "http://10.10.0.202:8000" `
#       -StationKey "<KEY>"
#   Task Scheduler (no extra tools):
#     .\deploy_station_agent.ps1 ... -UseTaskScheduler
param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$WatchDir,
    [Parameter(Mandatory=$true)][string]$MesBaseUrl,
    [Parameter(Mandatory=$true)][string]$StationKey,
    [string]$ServiceName = "StationIngest",
    [switch]$UseTaskScheduler
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) { throw "Exe not found: $ExePath" }
New-Item -ItemType Directory -Force -Path $WatchDir | Out-Null

$exeDir = Split-Path -Parent $ExePath

# 1. Write station_agent.ini next to the exe.
$ini = Join-Path $exeDir "station_agent.ini"
@"
[agent]
watch_dir = $WatchDir
mes_base_url = $MesBaseUrl
station_key = $StationKey
archive_dir = $(Join-Path $WatchDir 'Archive')
error_dir = $(Join-Path $WatchDir 'Errors')
scan_interval = 30
"@ | Set-Content -Path $ini -Encoding UTF8
Write-Host "Wrote config: $ini"

# 2. Register the background service.
if ($UseTaskScheduler) {
    $action   = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory $exeDir
    $trigger  = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $ServiceName -Action $action -Trigger $trigger `
        -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
    Write-Host "Registered Scheduled Task '$ServiceName' (runs at startup as SYSTEM, hidden)."
    Start-ScheduledTask -TaskName $ServiceName
} else {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) {
        throw "NSSM not found. Install NSSM (https://nssm.cc) or pass -UseTaskScheduler."
    }
    $nssmPath = $nssm.Source
    & $nssmPath install $ServiceName $ExePath
    & $nssmPath set $ServiceName AppDirectory $exeDir
    & $nssmPath set $ServiceName Start SERVICE_AUTO_START
    & $nssmPath set $ServiceName AppExit Default Restart
    & $nssmPath set $ServiceName AppRestartDelay 5000
    & $nssmPath start $ServiceName
    Write-Host "Installed NSSM service '$ServiceName' (auto-start, restarts on exit)."
}

Write-Host "Agent logs: $(Join-Path $exeDir 'station_push_agent.log')"
