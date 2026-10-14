#Requires -Version 5.1
<#
.SYNOPSIS
  Flutter host + PyInstaller sidecar, staged dist layout, smoke check,
  optional Inno Setup installer.

.EXAMPLE
  .\scripts\build-windows.ps1

.EXAMPLE
  .\scripts\build-windows.ps1 -SkipPyInstaller -SkipInno
#>
param(
    [string] $OutputDir = "",
    [string] $BuildPython = "",
    [switch] $SkipPyInstaller,
    [switch] $SkipFlutter,
    [switch] $SkipInno,
    [switch] $SkipModels,
    [switch] $Portable,
    [switch] $ServerZip
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
    param([string] $Override = "")
    if ($Override) {
        $path = $Override
        if (-not [System.IO.Path]::IsPathRooted($path)) {
            $path = Join-Path $RepoRoot $path
        }
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Build Python not found: $path"
        }
        return $path
    }
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

function Resolve-Flutter {
    $onPath = Get-Command flutter -ErrorAction SilentlyContinue
    if ($onPath) {
        return $onPath.Source
    }
    $local = Join-Path $env:LOCALAPPDATA 'flutter\bin\flutter.bat'
    if (Test-Path -LiteralPath $local) {
        return $local
    }
    throw "flutter not found. Add Flutter to PATH or install the SDK to %LOCALAPPDATA%\flutter."
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

# torch is not bundled: runtime packs ship separately (specs/030).
$Python = Resolve-BuildPython -Override $BuildPython
$version = Get-AppVersion -Python $Python
Write-Host "==> Version $version"
Invoke-Checked { & $Python (Join-Path $RepoRoot 'scripts\build-runtime-manifest.py') } 'fixed catalogs before build'
Invoke-Checked { & $Python (Join-Path $RepoRoot 'scripts\release_candidate.py') 'stamp-build' } 'record build source'

$DistDir = Join-Path $RepoRoot 'dist\ImageLocalizationTool'
$SidecarBuildDir = Join-Path $RepoRoot 'dist\ilt_sidecar'
$FlutterReleaseDir = Join-Path $RepoRoot 'apps\desktop\build\windows\x64\runner\Release'
$Spec = Join-Path $RepoRoot 'ImageLocalizationTool.spec'

# Frozen stdlib is incomplete (torch needs timeit etc.); ship the full zip.
Write-Host "==> Stage stdlib.zip"
Invoke-Checked {
    & $Python (Join-Path $RepoRoot 'scripts\build-stdlib-zip.py')
} 'build-stdlib-zip.py'

# Layout: {dist}/desktop = Flutter host, {dist}/sidecar = PyInstaller bundle,
# web/ and fonts/ at the dist root (models optional, copied below).

if (-not $SkipFlutter) {
    $Flutter = Resolve-Flutter
    Push-Location (Join-Path $RepoRoot 'apps\desktop')
    try {
        Invoke-Checked {
            & $Flutter build windows --release --build-name=$version --build-number=1
        } 'flutter build windows --release'
    } finally {
        Pop-Location
    }
    $flutterExe = Join-Path $FlutterReleaseDir 'ImageLocalizationTool.exe'
    if (-not (Test-Path -LiteralPath $flutterExe)) {
        throw "Flutter host exe not found: $flutterExe"
    }
} else {
    Write-Host "Skipping Flutter build (-SkipFlutter)."
}

if (-not $SkipPyInstaller) {
    & $Python -c "import PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed for $Python. Install it with: $Python -m pip install pyinstaller"
    }
    Invoke-Checked {
        & $Python -m PyInstaller $Spec --clean --noconfirm
    } 'PyInstaller ImageLocalizationTool.spec'
    $builtExe = Join-Path $SidecarBuildDir 'ImageLocalizationTool.exe'
    if (-not (Test-Path -LiteralPath $builtExe)) {
        throw "Sidecar exe not found: $builtExe"
    }
} else {
    Write-Host "Skipping PyInstaller (-SkipPyInstaller)."
}

if (-not (Test-Path -LiteralPath $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
}

# Remove files of the pre-cutover layout (root exe + _internal) so they can
# neither ship nor be picked up by the installer.
$staleExe = Join-Path $DistDir 'ImageLocalizationTool.exe'
if (Test-Path -LiteralPath $staleExe) {
    Write-Host "==> Remove stale root exe"
    Remove-Item -LiteralPath $staleExe -Force
}
$staleInternal = Join-Path $DistDir '_internal'
if (Test-Path -LiteralPath $staleInternal) {
    Write-Host "==> Remove stale root _internal"
    Remove-Item -LiteralPath $staleInternal -Recurse -Force
}

$hostDir = Join-Path $DistDir 'desktop'
if (Test-Path -LiteralPath $FlutterReleaseDir) {
    if (Test-Path -LiteralPath $hostDir) {
        Remove-Item -LiteralPath $hostDir -Recurse -Force
    }
    Write-Host "==> Stage desktop from $FlutterReleaseDir"
    New-Item -ItemType Directory -Path $hostDir -Force | Out-Null
    Copy-Item -Path (Join-Path $FlutterReleaseDir '*') -Destination $hostDir -Recurse -Force
} elseif (-not (Test-Path -LiteralPath (Join-Path $hostDir 'ImageLocalizationTool.exe'))) {
    throw "No Flutter build found: $FlutterReleaseDir. Run without -SkipFlutter."
}

$sidecarDir = Join-Path $DistDir 'sidecar'
if (Test-Path -LiteralPath $SidecarBuildDir) {
    if (Test-Path -LiteralPath $sidecarDir) {
        Remove-Item -LiteralPath $sidecarDir -Recurse -Force
    }
    Write-Host "==> Stage sidecar from $SidecarBuildDir"
    New-Item -ItemType Directory -Path $sidecarDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $SidecarBuildDir 'ImageLocalizationTool.exe') -Destination $sidecarDir -Force
    Copy-Item -LiteralPath (Join-Path $SidecarBuildDir '_internal') -Destination $sidecarDir -Recurse -Force
} elseif (-not (Test-Path -LiteralPath (Join-Path $sidecarDir 'ImageLocalizationTool.exe'))) {
    throw "No sidecar build found: $SidecarBuildDir. Run without -SkipPyInstaller."
}

# The spec stages web/ and fonts from COLLECT. Repeat for the dist root so the
# layout is complete even if that hook timing changes. models stay outside _internal.
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

$smoke = Join-Path $RepoRoot 'scripts\smoke_dist.py'
& $Python $smoke $DistDir '--expect-no-torch'
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

if ($Portable) {
    Invoke-Checked {
        & (Join-Path $RepoRoot 'scripts\package-portable.ps1')
    } 'package-portable.ps1'
}
if ($ServerZip) {
    Invoke-Checked {
        & (Join-Path $RepoRoot 'scripts\package-server.ps1')
    } 'package-server.ps1'
}

Write-Host ""
Write-Host "Windows build:" -ForegroundColor Green
Write-Host "  $(Join-Path $DistDir 'desktop\ImageLocalizationTool.exe')"
Write-Host "  $DistDir"
Invoke-Checked { & $Python (Join-Path $RepoRoot 'scripts\release_candidate.py') 'verify-build' } 'verify unchanged build source'
