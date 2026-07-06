#Requires -Version 5.1
<#
.SYNOPSIS
  Start Docker Compose with config/.env.compose (required for credential interpolation).

.EXAMPLE
  .\scripts\dev\compose-up.ps1
  .\scripts\dev\compose-up.ps1 up -d postgres redis
  .\scripts\dev\compose-up.ps1 ps
  .\scripts\dev\compose-up.ps1 -SkipBuild up -d
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EnvFile = Join-Path $ProjectRoot "config\.env.compose"
$ExampleFile = Join-Path $ProjectRoot "config\.env.compose.example"

if (-not (Test-Path $EnvFile)) {
    if (-not (Test-Path $ExampleFile)) {
        Write-Error "Missing config/.env.compose and config/.env.compose.example"
        exit 1
    }
    Write-Host "[INFO] Creating config/.env.compose from example..."
    Copy-Item $ExampleFile $EnvFile
    Write-Warning "Using placeholder credentials from example; edit config/.env.compose if needed."
}

if ($ComposeArgs.Count -eq 0) {
    $ComposeArgs = @("up", "-d")
}

$shouldBuildApi = -not $SkipBuild -and (
    ($ComposeArgs.Count -ge 1 -and $ComposeArgs[0] -eq "up")
)

Push-Location $ProjectRoot
try {
    Write-Host "[INFO] Rendering Grafana clinical alert contact point..."
    & python (Join-Path $ProjectRoot "scripts\observability\render_grafana_alert_contact.py")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if ($shouldBuildApi) {
        Write-Host "[INFO] Building vita-api image (root modules must match Dockerfile)..."
        & docker compose --env-file config/.env.compose build vita-api
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }

    & docker compose --env-file config/.env.compose @ComposeArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
