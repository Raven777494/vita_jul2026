# HSS rollback wrapper (Windows PowerShell).
# Calls scripts/deploy/rollback.sh with PREVIOUS_IMAGE_TAG set.
#
# Windows note: WSL/Git bash often does NOT inherit PowerShell $env: variables.
# This script passes PREVIOUS_IMAGE_TAG inline via bash -c.
#
# Usage:
#   .\scripts\deploy\rollback.ps1 -PreviousImageTag drill-before
#   $env:PREVIOUS_IMAGE_TAG = "drill-before"; .\scripts\deploy\rollback.ps1

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$PreviousImageTag = $env:PREVIOUS_IMAGE_TAG
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($PreviousImageTag)) {
    Write-Error "[FAIL] Provide -PreviousImageTag or set `$env:PREVIOUS_IMAGE_TAG"
}

if (-not (Test-Path "config\.env.compose")) {
    Write-Error "[FAIL] config\.env.compose missing. Run from repo root with compose env configured."
}

Remove-Item Env:\VITA_API_IMAGE -ErrorAction SilentlyContinue

# Escape single quotes for bash single-quoted string
$tagForBash = $PreviousImageTag.Replace("'", "'\''")

& bash -c "export PREVIOUS_IMAGE_TAG='${tagForBash}'; unset VITA_API_IMAGE; exec scripts/deploy/rollback.sh"
exit $LASTEXITCODE
