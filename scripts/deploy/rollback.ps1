# HSS rollback wrapper (Windows PowerShell).
# Calls scripts/deploy/rollback.sh with PREVIOUS_IMAGE_TAG set.
#
# Usage:
#   .\scripts\deploy\rollback.ps1 -PreviousImageTag drill-before
#   .\scripts\deploy\rollback.ps1 -PreviousImageTag c6888b6

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PreviousImageTag
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

if (-not (Test-Path "config\.env.compose")) {
    Write-Error "[FAIL] config\.env.compose missing. Run from repo root with compose env configured."
}

$env:PREVIOUS_IMAGE_TAG = $PreviousImageTag
Remove-Item Env:\VITA_API_IMAGE -ErrorAction SilentlyContinue

& bash scripts/deploy/rollback.sh
exit $LASTEXITCODE
