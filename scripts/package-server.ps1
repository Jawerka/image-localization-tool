#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Windows server zip: sidecar + web/fonts + deploy.cmd.

.DESCRIPTION
  Server layout is portable: empty data/, models/ and runtime/ ship next to
  the exe, deploy.cmd runs --deploy all (models + torch + argos) and then
  starts the headless remote API on the configured port.

.EXAMPLE
  .\scripts\package-server.ps1
#>
param(
    [string] $DistDir = "",
    [string] $OutputDir = "",
    [string] $Python = ""
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-BuildPython {
    param([string] $Override = '')
    if ($Override) { return $Override }
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) { return $venvPy }
    $releasePy = Join-Path $RepoRoot 'venv-release\Scripts\python.exe'
    if (Test-Path -LiteralPath $releasePy) { return $releasePy }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw 'python.exe not found; pass -Python.'
}

$Python = Resolve-BuildPython -Override $Python
$verSnippet = 'import sys; from pathlib import Path; root = Path(sys.argv[1]); sys.path.insert(0, str(root)); from scripts.smoke_dist import read_app_version; print(read_app_version(root))'
$version = (& $Python -c $verSnippet $RepoRoot).Trim()
Write-Host "==> Version $version"

if ([string]::IsNullOrWhiteSpace($DistDir)) {
    $DistDir = Join-Path $RepoRoot 'dist\ImageLocalizationTool'
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $RepoRoot 'dist'
}
$sidecarExe = Join-Path $DistDir 'sidecar\ImageLocalizationTool.exe'
if (-not (Test-Path -LiteralPath $sidecarExe)) {
    throw "Sidecar not found: $sidecarExe. Run scripts\build-windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$stage = Join-Path $RepoRoot 'build\server-win64\ImageLocalizationTool'
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null

Copy-Item -LiteralPath $sidecarExe -Destination (Join-Path $stage 'ImageLocalizationTool.exe')
Copy-Item -LiteralPath (Join-Path $DistDir 'sidecar\_internal') -Destination (Join-Path $stage '_internal') -Recurse
Copy-Item -LiteralPath (Join-Path $DistDir 'web') -Destination (Join-Path $stage 'web') -Recurse
if (Test-Path -LiteralPath (Join-Path $DistDir 'fonts')) {
    Copy-Item -LiteralPath (Join-Path $DistDir 'fonts') -Destination (Join-Path $stage 'fonts') -Recurse
}
foreach ($folder in @('data', 'models', 'runtime')) {
    $path = Join-Path $stage $folder
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $path '.keep') -Force | Out-Null
}

$deployCmd = @"
@echo off
rem Image Localization Tool server: deploy components, then headless remote API.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "ImageLocalizationTool.exe" (
  echo ImageLocalizationTool.exe not found
  exit /b 1
)
echo Deploying components (models, torch, argos)...
ImageLocalizationTool.exe --deploy all
if errorlevel 1 (
  echo Deploy failed
  exit /b 1
)
echo Starting headless server on port 8765 (Ctrl+C to stop)...
ImageLocalizationTool.exe --headless --remote
endlocal
"@
Set-Content -LiteralPath (Join-Path $stage 'deploy.cmd') -Value $deployCmd -Encoding ASCII

$zip = Join-Path $OutputDir "ImageLocalizationTool-$version-server-win64.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
Write-Host "Server zip: $zip" -ForegroundColor Green
Write-Host ("  {0:N1} MB" -f ((Get-Item -LiteralPath $zip).Length / 1MB))

exit 0
