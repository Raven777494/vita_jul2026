# Archive an ops evidence file into the local _ops_archive directory.
#
# D:\ops was never created — use repo-local _ops_archive (gitignored) instead.
#
# Usage:
#   .\scripts\ops\archive_ops_record.ps1 -Source "logs\webhook-drill-proof.jsonl" -Name "WEBHOOK-DRILL-2026-07-001.jsonl"
#   .\scripts\ops\archive_ops_record.ps1 -Source "D:\vita\logs\mon-steady-state-record.jsonl" -Name "MON-RECORD-2026-07-001.jsonl"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [string]$Name,

    [Parameter(Mandatory = $false)]
    [string]$ArchiveRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if ([string]::IsNullOrWhiteSpace($ArchiveRoot)) {
    $ArchiveRoot = Join-Path $RepoRoot "_ops_archive"
}

if (-not (Test-Path $Source)) {
    Write-Error "[FAIL] Source not found: $Source"
}

New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null
$dest = Join-Path $ArchiveRoot $Name
Copy-Item -Path $Source -Destination $dest -Force
Write-Host "[OK] Archived: $dest"
Write-Host "[INFO] Directory _ops_archive is gitignored — do not commit evidence files"
