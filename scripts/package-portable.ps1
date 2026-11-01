#Requires -Version 5.1
<#
.SYNOPSIS
  Build the portable zip from dist: app + empty data/, models/, runtime/.

.DESCRIPTION
  Windows ships only as this portable ZIP. Empty directories are pre-created
  (plus .keep markers) so extractors that drop empty folders keep the layout;
  the app writes all mutable data to data/ next to the program.

.EXAMPLE
  .\scripts\package-portable.ps1
#>
param(
    [string] $DistDir = "",
    [string] $OutputDir = "",
    [string] $Python = "",
    [switch] $FullCpu,
    [string] $ComponentSource = "",
    [switch] $UsePreparedStage,
    [string] $ArchiveToolDir = ""
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
function Copy-ReleaseNotices {
    param([string] $Destination)
    & $Python (Join-Path $PSScriptRoot 'pack_notices.py') $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Copying license notices failed' }
}

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
if ($FullCpu) { $stage = Join-Path $RepoRoot 'build\portable-full\ImageLocalizationTool' }
if (-not ([IO.Path]::GetFullPath($stage).StartsWith([IO.Path]::GetFullPath((Join-Path $RepoRoot 'build')) + [IO.Path]::DirectorySeparatorChar))) {
    throw 'Invalid portable staging path'
}
if ($UsePreparedStage -and -not $FullCpu) { throw 'UsePreparedStage requires FullCpu' }
if ($UsePreparedStage) {
    foreach ($name in @('desktop', 'sidecar', 'web', 'fonts')) {
        $sourceApp = Join-Path $DistDir $name
        $targetApp = [IO.Path]::GetFullPath((Join-Path $stage $name))
        if (-not $targetApp.StartsWith([IO.Path]::GetFullPath($stage) + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid app refresh path' }
        & robocopy $sourceApp $targetApp /MIR /XJ /R:1 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np
        if ($LASTEXITCODE -ge 8) { throw 'Refreshing prepared app failed' }
    }
}
if (-not $UsePreparedStage) {
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null

# Copy the app without personal state: top-level models/runtime/data stay empty.
# /XD with a full path only: a bare name excludes directories at any depth
# and would drop desktop\data (Flutter assets), cv2\data, rapidocr\models.
$excludedDirs = @('models', 'runtime', 'data', '.resources', '.downloads', '.builtin', 'components') |
    ForEach-Object { Join-Path $DistDir $_ }
$robocopyArgs = @(
    $DistDir, $stage, '/E', '/XD') + $excludedDirs + @(
    '/XF', '.installer.lock', 'preparation.json', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np'
)
& robocopy @robocopyArgs
$code = $LASTEXITCODE
if ($code -ge 8) {
    throw "robocopy failed with exit code $code"
}

# Enforce the portable packaging contract after copying: discard the local
# top-level model payload, while keeping nested sidecar runtime assets such as
# sidecar\_internal\rapidocr\models.
$topLevelModels = Join-Path $stage 'models'
if (Test-Path -LiteralPath $topLevelModels) {
    Remove-Item -LiteralPath $topLevelModels -Recurse -Force
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

if ($FullCpu) {
    $prepareArgs = @('--stage', $stage)
    if ($ComponentSource) { $prepareArgs += @('--component-source', $ComponentSource) }
    & $Python (Join-Path $PSScriptRoot 'prepare-full-portable.py') @prepareArgs
    if ($LASTEXITCODE -ne 0) { throw 'Full CPU preparation failed; no archive produced' }
}
}
if ($FullCpu) {
    foreach ($dll in @('msvcp140.dll', 'MSVCP140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')) {
        $runtimeDll = Join-Path $stage ('sidecar\_internal\' + $dll)
        if (-not (Test-Path -LiteralPath $runtimeDll -PathType Leaf)) { throw "Host runtime DLL missing: $dll" }
        Copy-Item -LiteralPath $runtimeDll -Destination (Join-Path $stage 'desktop') -Force
    }
    if (-not $ArchiveToolDir) { $ArchiveToolDir = Join-Path $env:ProgramFiles '7-Zip' }
    $archiveToolTarget = Join-Path $stage 'tools\7zip'
    New-Item -ItemType Directory -Path $archiveToolTarget -Force | Out-Null
    foreach ($file in @('7z.exe', '7z.dll', 'License.txt')) {
        $toolSource = Join-Path $ArchiveToolDir $file
        if (-not (Test-Path -LiteralPath $toolSource -PathType Leaf)) { throw "Install 7-Zip on the build host or pass ArchiveToolDir: $file" }
        Copy-Item -LiteralPath $toolSource -Destination $archiveToolTarget -Force
    }
    $personal = @(Get-ChildItem -LiteralPath (Join-Path $stage 'data') -Force -Recurse -File | Where-Object { $_.Name -ne '.keep' })
    if ($personal.Count) { throw 'Full portable data must be empty' }
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'distribution.json'))) { throw 'Prepared profile marker missing' }
    $checkFile = Join-Path $stage 'verify-profile.json'
    [IO.File]::WriteAllText($checkFile, '{"kind":"verify-distribution"}', (New-Object Text.UTF8Encoding($false)))
    $savedInstall = $env:ILT_INSTALL_ROOT
    $savedComponents = $env:ILT_COMPONENT_ROOT
    $savedData = $env:ILT_DATA_DIR
    try {
        $env:ILT_INSTALL_ROOT = $stage
        $env:ILT_COMPONENT_ROOT = $stage
        $env:ILT_DATA_DIR = Join-Path $stage 'data'
        $process = Start-Process -FilePath (Join-Path $stage 'sidecar\ImageLocalizationTool.exe') -ArgumentList @('--component-check', ('"' + $checkFile + '"')) -WorkingDirectory $stage -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw 'Prepared profile verification failed' }
    } finally {
        $env:ILT_INSTALL_ROOT = $savedInstall
        $env:ILT_COMPONENT_ROOT = $savedComponents
        $env:ILT_DATA_DIR = $savedData
        Remove-Item -LiteralPath $checkFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $stage 'check.result.json') -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $stage '.installer.lock') -Force -ErrorAction SilentlyContinue
    $profilePath = Join-Path $stage 'distribution.json'
    $profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
    $profile.version = $version
    $profile | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $profilePath -Encoding utf8
    $cleanData = [IO.Path]::GetFullPath((Join-Path $stage 'data'))
    if (-not $cleanData.StartsWith([IO.Path]::GetFullPath($stage) + [IO.Path]::DirectorySeparatorChar)) { throw 'Invalid clean data path' }
    Remove-Item -LiteralPath $cleanData -Recurse -Force
    New-Item -ItemType Directory -Path $cleanData -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $cleanData '.keep') -Force | Out-Null
}

# User data is never part of a portable release. Updates move these directories
# from the active installation into the staged release during activation.
$manifest = [ordered]@{
    schema = 1
    version = $version
    platform = 'windows-x64'
    host = 'desktop/ImageLocalizationTool.exe'
    sidecar = 'sidecar/ImageLocalizationTool.exe'
    web = 'web/index.html'
}
if ($FullCpu) {
    $manifest['profile'] = 'cpu-full'
    $manifest['archive_tool'] = 'tools/7zip/7z.exe'
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stage 'release.json') -Encoding utf8
foreach ($scriptName in @('update-windows.ps1', 'rollback-windows.ps1', 'windows-update-common.ps1')) {
    if ($FullCpu) { continue }
    $source = Join-Path $PSScriptRoot $scriptName
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Windows updater source missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $stage $scriptName) -Force
}

Copy-ReleaseNotices -Destination $stage

$zip = Join-Path $OutputDir "ImageLocalizationTool-$version-windows-x64-portable.zip"
if ($FullCpu) { $zip = Join-Path $OutputDir "ImageLocalizationTool-$version-windows-x64-portable-cpu-full.zip" }
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $true)
Write-Host "Portable zip: $zip" -ForegroundColor Green
Write-Host ("  {0:N1} MB" -f ((Get-Item -LiteralPath $zip).Length / 1MB))

exit 0
