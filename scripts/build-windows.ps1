#Requires -Version 5.1
<#
.SYNOPSIS
  PyInstaller onedir, models beside the exe, smoke check, optional Inno Setup installer.

.EXAMPLE
  .\scripts\build-windows.ps1

.EXAMPLE
  .\scripts\build-windows.ps1 -SkipPyInstaller -SkipInno
#>
param(
    [string] $OutputDir = "",
    [switch] $SkipPyInstaller,
    [switch] $SkipInno,
    [switch] $SkipModels
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
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) {
        return $venvPy
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) {
        Write-Host "venv\Scripts\python.exe not found; using $($onPath.Source)"
        return $onPath.Source
    }
    throw "python.exe not found. Create venv, install requirements.txt and pyinstaller, then retry."
}

function Get-AppVersion {
    param([string]$Python)
    $snippet = 'import sys; from pathlib import Path; root = Path(sys.argv[1]); sys.path.insert(0, str(root)); from scripts.smoke_dist import read_app_version; print(read_app_version(root))'
    $versionRaw = & $Python -c $snippet $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Reading __version__ from src/app/__init__.py failed with exit code $LASTEXITCODE"
    }
    $version = ([string]$versionRaw).Trim()
    if ($version -notmatch '^[0-9]+(\.[0-9]+){1,3}([A-Za-z0-9.+-]*)?$') {
        throw "Version from src/app/__init__.py is not a dotted number: $version"
    }
    return $version
}

function Find-Iscc {
    $candidates = @()
    $onPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($onPath) {
        $candidates += $onPath.Source
    }
    $candidates += @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Copy-ModelsBesideExe {
    param([string]$DistDir)
    $source = Join-Path $RepoRoot 'models'
    if (-not (Test-Path -LiteralPath $source)) {
        Write-Host "models directory not found; dist will not include models."
        return
    }
    if (-not (Test-Path -LiteralPath $DistDir)) {
        Write-Host "Dist directory not found; models were not copied: $DistDir"
        return
    }
    $dest = Join-Path $DistDir 'models'
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
    }
    Write-Host "==> Copy models to $dest"
    Copy-Item -LiteralPath $source -Destination $dest -Recurse -Force
}

# torch stays in the bundle. Do not add it to spec excludes.
$Python = Resolve-BuildPython
$version = Get-AppVersion -Python $Python
Write-Host "==> Version $version"

$DistDir = Join-Path $RepoRoot 'dist\ImageLocalizationTool'
$Spec = Join-Path $RepoRoot 'ImageLocalizationTool.spec'

if (-not $SkipPyInstaller) {
    & $Python -c "import PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed for $Python. Install it with: $Python -m pip install pyinstaller"
    }
    Invoke-Checked {
        & $Python -m PyInstaller $Spec --clean --noconfirm
    } 'PyInstaller ImageLocalizationTool.spec'
    $builtExe = Join-Path $DistDir 'ImageLocalizationTool.exe'
    if (-not (Test-Path -LiteralPath $builtExe)) {
        throw "Onedir exe not found: $builtExe"
    }
} else {
    Write-Host "Skipping PyInstaller (-SkipPyInstaller)."
}

# The spec stages web/ and fonts from COLLECT. Repeat after PyInstaller so the
# onedir root is complete even if that hook timing changes. models stay out of _internal.
if (Test-Path -LiteralPath $DistDir) {
    $stage = 'import sys; from pathlib import Path; root = Path(sys.argv[1]); dist = Path(sys.argv[2]); sys.path.insert(0, str(root)); from scripts.smoke_dist import stage_runtime_files; stage_runtime_files(dist, root)'
    Write-Host "==> Stage web and fonts"
    & $Python -c $stage $RepoRoot $DistDir
    if ($LASTEXITCODE -ne 0) {
        throw "Staging web and fonts failed with exit code $LASTEXITCODE"
    }
    if ($SkipModels) {
        $modelsDest = Join-Path $DistDir 'models'
        if (Test-Path -LiteralPath $modelsDest) {
            Write-Host "==> Remove models from dist"
            Remove-Item -LiteralPath $modelsDest -Recurse -Force
        }
    } else {
        Copy-ModelsBesideExe -DistDir $DistDir
    }
}

$smoke = Join-Path $RepoRoot 'scripts\smoke_dist.py'
& $Python $smoke $DistDir
if ($LASTEXITCODE -ne 0) {
    $smokeCode = $LASTEXITCODE
    Write-Host "smoke_dist.py failed with exit code $smokeCode"
    exit $smokeCode
}

$iscc = Find-Iscc
if ($SkipInno) {
    if (-not $iscc) {
        Write-Host "Inno Setup (ISCC.exe) not found. -SkipInno is set, so the installer step is skipped."
    } else {
        Write-Host "Skipping Inno Setup (-SkipInno)."
    }
} elseif (-not $iscc) {
    Write-Host "Inno Setup (ISCC.exe) not found."
    Write-Host "Install Inno Setup 6.1 or newer, or re-run with -SkipInno."
    throw "ISCC.exe not found. Installer was not built."
} else {
    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        $OutputDir = Join-Path $RepoRoot 'dist'
    }
    if (-not (Test-Path -LiteralPath $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    $outputResolved = (Resolve-Path -LiteralPath $OutputDir).Path
    $distResolved = (Resolve-Path -LiteralPath $DistDir).Path
    $iss = Join-Path $RepoRoot 'installer\ImageLocalizationTool.iss'
    Write-Host "==> Inno Setup $version"
    & $iscc $iss "/DAppVersion=$version" "/DDistDir=$distResolved" "/DOutputDir=$outputResolved"
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC failed with exit code $LASTEXITCODE"
    }
    $setup = Join-Path $outputResolved "ImageLocalizationTool-$version-windows-x64-setup.exe"
    if (-not (Test-Path -LiteralPath $setup)) {
        throw "Installer was not created: $setup"
    }
    Write-Host "Created $setup"
}

Write-Host ""
Write-Host "Windows build:" -ForegroundColor Green
Write-Host "  $(Join-Path $DistDir 'ImageLocalizationTool.exe')"
Write-Host "  $DistDir"
