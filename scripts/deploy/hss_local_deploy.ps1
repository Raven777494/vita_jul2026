# HSS local staging deploy (Windows PowerShell) — D2-B go-live 1.3
#
# Use when staging host is local HSS (D:\vita) without GHA SSH deploy.
# Equivalent acceptance to D2 GHA dry_run=false for solo-operator mode.
#
# Usage:
#   .\scripts\deploy\hss_local_deploy.ps1
#   .\scripts\deploy\hss_local_deploy.ps1 -IncludeMonitoring
#   .\scripts\deploy\hss_local_deploy.ps1 -SkipPull -ImageTag local

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Branch = "develop",

    [Parameter(Mandatory = $false)]
    [string]$ImageTag = "latest",

    [Parameter(Mandatory = $false)]
    [switch]$SkipPull,

    [Parameter(Mandatory = $false)]
    [switch]$SkipBuild,

    [Parameter(Mandatory = $false)]
    [switch]$IncludeMonitoring
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host "[DEPLOY] $Message"
}

if (-not (Test-Path "config\.env.compose")) {
    Write-Error "[FAIL] config\.env.compose missing. Configure HSS compose env before deploy."
}

if (-not $SkipPull) {
    Write-Step "git pull origin $Branch"
    git pull origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[FAIL] git pull failed"
    }
}

$sha = (git rev-parse --short HEAD).Trim()
Write-Step "commit $sha"

if (Test-Path "config\.env.compose") {
    Copy-Item "config\.env.compose" "config\.env.compose.backup" -Force
    Write-Step "backed up config\.env.compose"
}

Remove-Item Env:\VITA_API_IMAGE -ErrorAction SilentlyContinue

if (-not $SkipBuild) {
    Write-Step "docker compose build postgres"
    docker compose --env-file config\.env.compose build postgres
    if ($LASTEXITCODE -ne 0) { Write-Error "[FAIL] postgres build failed" }

    Write-Step "docker build vita-api:$ImageTag"
    docker build -t "vita-api:$ImageTag" -t "vita-api:$sha" .
    if ($LASTEXITCODE -ne 0) { Write-Error "[FAIL] vita-api build failed" }
}

$services = @("postgres", "redis", "vita-api")
if ($IncludeMonitoring) {
    $services += @("victorialogs", "vmsingle", "grafana")
}

Write-Step ("docker compose up -d " + ($services -join ", "))
docker compose --env-file config\.env.compose up -d @services --wait
if ($LASTEXITCODE -ne 0) { Write-Error "[FAIL] compose up failed" }

Write-Step "smoke_check.sh"
& bash scripts/deploy/smoke_check.sh
if ($LASTEXITCODE -ne 0) { Write-Error "[FAIL] smoke checks failed" }

Write-Host "[OK] HSS local deploy complete (vita-api:$ImageTag @ $sha)"
Write-Host "[INFO] Record DEP-DRILL-YYYY-MM-NNN with commit $sha for go-live 1.3 (D2-B)"
