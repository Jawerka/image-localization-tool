#Requires -Version 5.1
<#
.SYNOPSIS
  Build runtime lock summaries from official wheels (schema 2).

.DESCRIPTION
  Runs scripts/build-runtime-locks.py for the win packs (torch-cpu, torch-cu128,
  argos): pip resolves pins without installing and downloads the wheels into
  dist/locks/stage; summaries land in dist/locks/packs.json, and full pin files
  locks/py310-<pack>-win.lock are written for the repository (commit them).

  The old .7z pipeline (build-runtime-packs.ps1) is DEPRECATED — see specs/032.

.EXAMPLE
  .\scripts\build-runtime-locks.ps1
  .\scripts\build-runtime-locks.ps1 -Variant cpu
  .\scripts\build-runtime-locks.ps1 -Variant argos -OutDir dist\locks
#>
param(
    [ValidateSet('all', 'cpu', 'cu128', 'argos')]
    [string] $Variant = 'all',
    [string] $OutDir = '',
    [string] $Python = ''
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Label)
    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Resolve-BuildPython {
    param([string] $Override = '')
    if ($Override) {
        return $Override
    }
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) {
        return $venvPy
    }
    $releasePy = Join-Path $RepoRoot 'venv-release\Scripts\python.exe'
    if (Test-Path -LiteralPath $releasePy) {
        return $releasePy
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }
    throw 'python.exe not found; pass -Python.'
}

$Python = Resolve-BuildPython -Override $Python
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $RepoRoot 'dist\locks'
}
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$LocksDir = Join-Path $RepoRoot 'locks'
$Script = Join-Path $RepoRoot 'scripts\build_runtime_locks.py'

$packs = @()
if ($Variant -eq 'all' -or $Variant -eq 'cpu') { $packs += 'torch-cpu' }
if ($Variant -eq 'all' -or $Variant -eq 'cu128') { $packs += 'torch-cu128' }
if ($Variant -eq 'all' -or $Variant -eq 'argos') { $packs += 'argos' }

foreach ($pack in $packs) {
    Invoke-Checked {
        & $Python $Script --pack $pack --os win --out $OutDir --lock-dir $LocksDir
    } "build-runtime-locks.py $pack (win)"
}

Write-Host ''
Write-Host 'Runtime lock summaries:' -ForegroundColor Green
Get-ChildItem -LiteralPath $OutDir -Filter '*.json' | ForEach-Object {
    Write-Host ("  {0} ({1:N1} KB)" -f $_.Name, ($_.Length / 1KB))
}
Get-ChildItem -LiteralPath $LocksDir -Filter 'py310-*-win.lock' -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host "  $($_.FullName)" }
