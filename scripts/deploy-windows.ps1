#Requires -Version 5.1
<#
.SYNOPSIS
  Mirror dist\ImageLocalizationTool into the local apps folder.

.EXAMPLE
  .\scripts\deploy-windows.ps1

.EXAMPLE
  .\scripts\deploy-windows.ps1 -Build -SkipInno

.EXAMPLE
  .\scripts\deploy-windows.ps1 -Dest "D:\Documents\apps\ImageLocalizationTool" -IncludeModels
#>
param(
    [string] $Dest = "D:\Documents\apps\ImageLocalizationTool",
    [switch] $Build,
    [switch] $SkipInno,
    [switch] $IncludeModels
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$DistDir = Join-Path $RepoRoot 'dist\ImageLocalizationTool'
$ExeName = 'ImageLocalizationTool.exe'

if ($Build) {
    $buildScript = Join-Path $PSScriptRoot 'build-windows.ps1'
    # Hashtable splat so -SkipInno binds as a switch, not as OutputDir.
    $buildArgs = @{ SkipInno = $true }
    if (-not $IncludeModels) {
        $buildArgs['SkipModels'] = $true
    }
    Write-Host "==> Build ($( ($buildArgs.Keys | ForEach-Object { "-$_" }) -join ' '))"
    & $buildScript @buildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "build-windows.ps1 failed with exit code $LASTEXITCODE"
    }
}

$builtExe = Join-Path $DistDir "desktop\$ExeName"
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "Dist host exe not found: $builtExe. Run with -Build or build first."
}

if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}

# User data that lives beside the app and must survive /MIR. Full destination
# paths only: a bare name would also drop nested source dirs such as
# desktop\data (Flutter assets) or rapidocr\models.
$userDirs = @('models', 'runtime', 'data', '.resources', '.downloads', '.builtin', 'components')
$exclude = @()
if (-not $IncludeModels) {
    # Source has no models to copy; exclude the dist copy path as well.
    $exclude += (Join-Path $DistDir 'models')
    Write-Host "==> Mirror (excluding models) $DistDir -> $Dest"
} else {
    Write-Host "==> Mirror (including models) $DistDir -> $Dest"
}
$protect = @()
foreach ($name in $userDirs) {
    if ($IncludeModels -and $name -eq 'models') {
        # -IncludeModels copies dist\models over the destination on purpose.
        continue
    }
    $protect += (Join-Path $Dest $name)
}
$exclude += $protect

# Remember which user dirs exist so the mirror cannot silently delete them.
$existingUserDirs = @($protect | Where-Object { Test-Path -LiteralPath $_ })

# /MIR keeps dest in sync with dist. Exit codes 0-7 are success for robocopy.
$robocopyArgs = @($DistDir, $Dest, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np')
if ($exclude.Count -gt 0) {
    $robocopyArgs += '/XD'
    $robocopyArgs += $exclude
}
& robocopy @robocopyArgs
$code = $LASTEXITCODE
if ($code -ge 8) {
    throw "robocopy failed with exit code $code"
}

$destExe = Join-Path $Dest 'desktop\ImageLocalizationTool.exe'
if (-not (Test-Path -LiteralPath $destExe)) {
    throw "Deploy incomplete: missing $destExe"
}
$destSidecar = Join-Path $Dest 'sidecar\ImageLocalizationTool.exe'
if (-not (Test-Path -LiteralPath $destSidecar)) {
    throw "Deploy incomplete: missing $destSidecar"
}
$destWeb = Join-Path $Dest 'web'
if (-not (Test-Path -LiteralPath $destWeb)) {
    throw "Deploy incomplete: missing $destWeb"
}
foreach ($userDir in $existingUserDirs) {
    if (-not (Test-Path -LiteralPath $userDir)) {
        throw "Deploy deleted user data: $userDir"
    }
}

Write-Host ""
Write-Host "Windows deploy OK:" -ForegroundColor Green
Write-Host "  $destExe"
Write-Host "  robocopy exit=$code"
