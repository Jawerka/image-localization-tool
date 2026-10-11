#Requires -Version 5.1
<#
.SYNOPSIS
  DEPRECATED (specs/032-runtime-wheelset): legacy .7z pack build. Use
  scripts/build-runtime-locks.ps1 - the runtime installs from official wheels.

.DESCRIPTION
  Builds runtime .7z packs (torch cpu/cu128, argos) from clean venvs.
  Creates build/runtime-venvs/<name>, installs pinned packages, then calls
  scripts/build-runtime-pack.py (it trims site-packages, writes LZMA2 .7z and
  updates dist/packs/packs.json with sha256 and size). The script interpreter
  must have py7zr; torch venvs do not need it.

.EXAMPLE
  .\scripts\build-runtime-packs.ps1
  .\scripts\build-runtime-packs.ps1 -Variant cpu
  .\scripts\build-runtime-packs.ps1 -Variant argos -OutDir dist\packs
#>
param(
    [ValidateSet('all', 'cpu', 'cu128', 'argos')]
    [string] $Variant = 'all',
    [string] $OutDir = '',
    [string] $Python = '',
    [switch] $RecreateVenvs
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$TorchVersion = '2.11.0'
$ArgosSpec = 'argostranslate @ git+https://github.com/argosopentech/argos-translate.git'
$CpuIndex = 'https://download.pytorch.org/whl/cpu'
$CudaIndex = 'https://download.pytorch.org/whl/cu128'

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

function Ensure-Venv {
    param(
        [string]$Path,
        [string[]]$Packages,
        [string]$IndexUrl = ''
    )
    $venvPy = Join-Path $Path 'Scripts\python.exe'
    if ($RecreateVenvs -and (Test-Path -LiteralPath $Path)) {
        Write-Host "==> Remove $Path"
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Invoke-Checked {
            & $Python -m venv $Path
        } "venv $Path"
    }
    Invoke-Checked {
        & $venvPy -m pip install --upgrade pip --quiet
    } "pip upgrade ($Path)"
    $pipArgs = @('-m', 'pip', 'install') + $Packages
    if ($IndexUrl) {
        $pipArgs += @('--index-url', $IndexUrl)
    }
    Invoke-Checked {
        & $venvPy @pipArgs
    } "pip install $($Packages -join ' ') ($Path)"
    return $venvPy
}

function Build-Pack {
    param(
        [string]$VenvPath,
        [string]$Kind,
        [string]$PackVariant,
        [string]$Platform
    )
    $script = Join-Path $RepoRoot 'scripts\build-runtime-pack.py'
    $packArgs = @($script, '--venv', $VenvPath, '--kind', $Kind, '--platform', $Platform, '--out', $OutDir)
    if ($Kind -eq 'torch') {
        $packArgs += @('--variant', $PackVariant)
    }
    Invoke-Checked {
        & $Python @packArgs
    } "build-runtime-pack.py $Kind/$PackVariant"
}

$Python = Resolve-BuildPython -Override $Python
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $RepoRoot 'dist\packs'
}
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$VenvRoot = Join-Path $RepoRoot 'build\runtime-venvs'

if ($Variant -eq 'all' -or $Variant -eq 'cpu') {
    $cpuVenv = Join-Path $VenvRoot 'torch-cpu'
    Ensure-Venv -Path $cpuVenv -Packages @("torch==$TorchVersion") -IndexUrl $CpuIndex | Out-Null
    Build-Pack -VenvPath $cpuVenv -Kind 'torch' -PackVariant 'cpu' -Platform 'win'
}

if ($Variant -eq 'all' -or $Variant -eq 'cu128') {
    $cudaVenv = Join-Path $VenvRoot 'torch-cu128'
    Ensure-Venv -Path $cudaVenv -Packages @("torch==$TorchVersion+cu128") -IndexUrl $CudaIndex | Out-Null
    Build-Pack -VenvPath $cudaVenv -Kind 'torch' -PackVariant 'cu128' -Platform 'win'
}

if ($Variant -eq 'all' -or $Variant -eq 'argos') {
    $argosVenv = Join-Path $VenvRoot 'argos'
    Ensure-Venv -Path $argosVenv -Packages @($ArgosSpec) | Out-Null
    Build-Pack -VenvPath $argosVenv -Kind 'argos' -PackVariant '' -Platform 'win'
}

Write-Host ''
Write-Host 'Runtime packs:' -ForegroundColor Green
Get-ChildItem -LiteralPath $OutDir -Filter '*.7z' | ForEach-Object {
    Write-Host ("  {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
}
Write-Host "  $(Join-Path $OutDir 'packs.json')"
