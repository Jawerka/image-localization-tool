#Requires -Version 5.1
<#
.SYNOPSIS
  Build the portable zip from dist: app + empty data/, models/, runtime/.

.DESCRIPTION
  Portable mode triggers when a data/ directory sits next to the program
  (src/app/paths.py). Empty directories are pre-created (plus .keep markers)
  so extractors that drop empty folders keep the layout.

.EXAMPLE
  .\scripts\package-portable.ps1
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
if (-not (Test-Path -LiteralPath (Join-Path $DistDir 'desktop\ImageLocalizationTool.exe'))) {
    throw "Dist not found: $DistDir. Run scripts\build-windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$stage = Join-Path $RepoRoot 'build\portable\ImageLocalizationTool'
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null

# Copy the app without personal state: top-level models/runtime/data stay empty.
# /XD with a full path only: a bare name excludes directories at any depth
# and would drop desktop\data (Flutter assets), cv2\data, rapidocr\models.
$excludedDirs = @('models', 'runtime', 'data') |
    ForEach-Object { Join-Path $DistDir $_ }
$robocopyArgs = @(
    $DistDir, $stage, '/E', '/XD') + $excludedDirs + @(
    '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np'
)
& robocopy @robocopyArgs
$code = $LASTEXITCODE
if ($code -ge 8) {
    throw "robocopy failed with exit code $code"
}

# Guard against losing nested directories: without Flutter assets the host will not start.
foreach ($required in @('desktop\data\flutter_assets', 'desktop\data\app.so', 'sidecar\ImageLocalizationTool.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $stage $required))) {
        throw "Portable staging incomplete: $required"
    }
}

foreach ($folder in @('data', 'models', 'runtime')) {
    $path = Join-Path $stage $folder
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $path '.keep') -Force | Out-Null
}

$zip = Join-Path $OutputDir "ImageLocalizationTool-$version-windows-x64-portable.zip"
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
Write-Host "Portable zip: $zip" -ForegroundColor Green
Write-Host ("  {0:N1} MB" -f ((Get-Item -LiteralPath $zip).Length / 1MB))

exit 0
