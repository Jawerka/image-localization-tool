#Requires -Version 5.1
<#
.SYNOPSIS
  Build unpacked Chromium extension and mirror it to the apps load path.

.EXAMPLE
  .\scripts\deploy-extension.ps1

.EXAMPLE
  .\scripts\deploy-extension.ps1 -Dest "D:\Documents\apps\extension\image-localization-tool"
#>
param(
    [string] $Dest = "D:\Documents\apps\extension\image-localization-tool",
    [switch] $SkipBuild
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-Python {
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) {
        return $venvPy
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }
    throw "python.exe not found. Activate venv or install Python."
}

$chromium = Join-Path $RepoRoot 'dist\chromium'
if (-not $SkipBuild) {
    $Python = Resolve-Python
    Write-Host "==> Build extension"
    & $Python (Join-Path $PSScriptRoot 'build-extension.py')
    if ($LASTEXITCODE -ne 0) {
        throw "build-extension.py failed with exit code $LASTEXITCODE"
    }
}

$manifest = Join-Path $chromium 'manifest.json'
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Chromium unpack not found: $manifest. Run without -SkipBuild."
}

if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}

Write-Host "==> Mirror $chromium -> $Dest"
& robocopy $chromium $Dest /MIR /NFL /NDL /NJH /NJS /nc /ns /np
$code = $LASTEXITCODE
if ($code -ge 8) {
    throw "robocopy failed with exit code $code"
}

$destManifest = Join-Path $Dest 'manifest.json'
if (-not (Test-Path -LiteralPath $destManifest)) {
    throw "Deploy incomplete: missing $destManifest"
}

Write-Host ""
Write-Host "Extension deploy OK:" -ForegroundColor Green
Write-Host "  $destManifest"
Write-Host "  Load unpacked in Chromium from: $Dest"
Write-Host "  robocopy exit=$code"
