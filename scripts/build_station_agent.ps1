# Build the standalone Windows executable for the station push agent.
# Requires PyInstaller:  pip install pyinstaller
# Run from the repo root:  .\scripts\build_station_agent.ps1
param(
    [string]$PyInstaller = "pyinstaller"
)

$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $PSScriptRoot   # mes_pft/
$agent = Join-Path $root "backend\app\scripts\station_push_agent.py"
$dist  = Join-Path $root "backend\app\static\agent"

& $PyInstaller --onefile --noconsole --clean `
    --name station_push_agent `
    --distpath $dist `
    --workpath (Join-Path $root "build\pyinstaller") `
    --specpath (Join-Path $root "build") `
    $agent

Write-Host ""
Write-Host "Built: $(Join-Path $dist 'station_push_agent.exe')"
