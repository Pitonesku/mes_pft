# deploy_odoo_addon_prod.ps1
# =============================================================================
# Deploy the tested mes_integration addon to the PRODUCTION Odoo and upgrade it.
#
# RUN ON THE PRODUCTION ODOO SERVER, from an elevated PowerShell, only after the
# addon passed the dev smoke tests (backend/scripts/smoke_test_*.py against the
# DEV Odoo on 8070):
#   1. copies C:\Odoodev\odoo_my_addons\mes_integration into the production
#      Odoo addons folder (Program Files) - the ONLY allowed way to touch it;
#   2. stops the Odoo Windows service, runs `odoo-bin -u mes_integration`,
#      starts the service again;
#   3. afterwards set in the MES production .env (C:\mes_system\.env):
#        ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true   (addon now signs timestamps)
#      and restart the MES_Server task.
#
# Adjust -Conf / -Db / -ServiceName / -OdooHome to your installation.
# =============================================================================
param(
    [string]$SourceAddon  = "C:\Odoodev\odoo_my_addons\mes_integration",
    [string]$OdooHome     = "C:\Program Files\Odoo 18.0.20260217",
    [string]$Conf         = "C:\Program Files\Odoo 18.0.20260217\server\odoo.conf",
    [string]$Db           = "odoo",
    [string]$ServiceName  = "OdooService",
    [switch]$UpgradeOnly  # skip the file copy (already deployed)
)

$ErrorActionPreference = "Stop"

$AddonsRoot = Join-Path $OdooHome "server\odoo\addons"
$Target     = Join-Path $AddonsRoot "mes_integration"
$OdooBin    = Join-Path $OdooHome "server\odoo-bin"
$Python     = Join-Path $OdooHome "python\python.exe"

if (-not (Test-Path $SourceAddon)) { throw "Source addon not found: $SourceAddon" }
if (-not (Test-Path $OdooBin))    { throw "odoo-bin not found: $OdooBin" }
if (-not (Test-Path $Python))     { throw "Odoo python not found: $Python" }
if (-not (Test-Path $Conf))       { throw "Odoo config not found: $Conf" }

Write-Host "=== Deploying mes_integration to PRODUCTION Odoo ==="

if (-not $UpgradeOnly) {
    Write-Host "1/3 Copying addon -> $Target"
    if (Test-Path $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
    Copy-Item -LiteralPath $SourceAddon -Destination $Target -Recurse
}

Write-Host "2/3 Stopping service '$ServiceName' + running module upgrade on '$Db'"
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$wasRunning = $false
if ($service) {
    if ($service.Status -ne "Stopped") { Stop-Service -Name $ServiceName -Force; $wasRunning = $true }
    Start-Sleep -Seconds 5
}

try {
    & $Python $OdooBin -c $Conf -d $Db -u mes_integration --stop-after-init
    if ($LASTEXITCODE -ne 0) { throw "odoo-bin -u mes_integration failed (exit $LASTEXITCODE)" }
} finally {
    if ($wasRunning) {
        Write-Host "3/3 Restarting service '$ServiceName'"
        Start-Service -Name $ServiceName
    } else {
        Write-Host "3/3 Service was already stopped - not restarted"
    }
}

Write-Host ""
Write-Host "DONE. Verify in Odoo: Manufacturing -> Orders -> the MO form shows"
Write-Host "'Cancel / Recall from MES' and mes_sync_status includes 'Recalled'."
Write-Host ""
Write-Host "Then on the MES production server: set ODOO_WEBHOOK_REQUIRE_TIMESTAMP=true"
Write-Host "in C:\mes_system\.env and restart the MES_Server task."
