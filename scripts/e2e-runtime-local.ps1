#Requires -Version 5.1
<#
.SYNOPSIS
  Сквозная локальная приёмка рантайма (specs/032-runtime-wheelset).

.DESCRIPTION
  Прогоняет всю последовательность ДО сборки и загрузки релиза:

  1. pytest: клиент колёс, генератор локов, манифест, гейт;
  2. канонические win-локи в dist/locks, сверка locks/ с закоммиченными;
  3. локальная копия сводки с file://-базой для установки;
  4. dev-`--deploy cpu`/`argos`, идемпотентность, битый sha;
  5. полная сборка (`build-windows.ps1 -SkipModels -Portable -ServerZip`) и
     frozen-установка из portable (`sidecar --deploy cpu`, импорт torch);
  6. `publish-release.ps1 -DryRun` (ничего не трогает в git/gh);
  7. гейт `check_release.py --deep` (Tier 1 HEAD + Tier 2 установка/import).

  Требуются: Flutter, PyInstaller, Inno Setup 6, интернет к PyPI и PyTorch CDN.
  Любой сбой — non-zero.

.EXAMPLE
  .\scripts\e2e-runtime-local.ps1
  .\scripts\e2e-runtime-local.ps1 -SkipBuild -KeepStages
  .\scripts\e2e-runtime-local.ps1 -Full     # + torch-cu128 (≈2.5 ГБ, NVIDIA)
#>
param(
    [string] $Python = '',
    [string] $BuildPython = '',
    [switch] $SkipBuild,
    [switch] $Full,
    [switch] $KeepStages
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$Stage = Join-Path $RepoRoot 'build\e2e'

function Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Label)
    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Assert {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw "Проверка не прошла: $Message"
    }
}

function Invoke-FrozenDeploy {
    # GUI-подсистемный exe: прямой вызов не даёт надёжный $LASTEXITCODE.
    param([string]$Exe, [string]$Target, [string]$Label)
    Write-Host "==> $Label"
    $process = Start-Process -FilePath $Exe -ArgumentList @('--deploy', $Target) `
        -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($process.ExitCode)"
    }
}

function Resolve-Python {
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

function Get-FileUri {
    param([string]$Path)
    return ([System.Uri]([System.IO.Path]::GetFullPath($Path))).AbsoluteUri
}

$Python = Resolve-Python -Override $Python
if (-not $BuildPython) {
    $releasePy = Join-Path $RepoRoot 'venv-release\Scripts\python.exe'
    $BuildPython = if (Test-Path -LiteralPath $releasePy) { $releasePy } else { $Python }
}

if (-not $KeepStages) {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
$LocksOut = Join-Path $Stage 'locks'
$RepoLocks = Join-Path $Stage 'locks-repo'
$ReleaseRoot = Join-Path $Stage 'release'
$ManifestPath = Join-Path $Stage 'manifest.json'
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
$UrlBase = Get-FileUri $ReleaseRoot

$verSnippet = 'import sys; from pathlib import Path; root = Path(sys.argv[1]); sys.path.insert(0, str(root)); from scripts.smoke_dist import read_app_version; print(read_app_version(root))'
$Version = (& $Python -c $verSnippet $RepoRoot).Trim()
Write-Host "Версия $Version, python $Python"

$packs = @('torch-cpu', 'argos')
if ($Full) { $packs += 'torch-cu128' }

# --- 1. pytest ---------------------------------------------------------------
Step '1. pytest: клиент колёс, генератор, манифест, гейт'
Invoke-Checked {
    & $Python -m pytest tests\unit\test_runtime.py tests\unit\test_runtime_locks.py `
        tests\unit\test_manifest_schema2.py tests\unit\test_check_release.py -q
} 'pytest unit (runtime wheelset)'

# --- 2. канонические лок-сводки и сверка с репозиторием ----------------------
Step '2. Канонические win-локи (dist\locks) и сверка locks\'
# Колесо argostranslate уже собрано и залито на rc: не пересобираем, иначе
# sha разойдётся с встроенным манифестом и опубликованным ассетом.
$canonicalArgosWheel = Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'dist\locks') `
    -Filter 'argostranslate-*.whl' -ErrorAction SilentlyContinue | Select-Object -First 1
foreach ($pack in $packs) {
    $lockArgs = @('scripts\build_runtime_locks.py', '--pack', $pack, '--os', 'win',
        '--out', 'dist\locks', '--lock-dir', $RepoLocks)
    if ($pack -eq 'argos' -and $null -ne $canonicalArgosWheel) {
        $lockArgs += @('--hosted-wheel', $canonicalArgosWheel.FullName)
    }
    Invoke-Checked { & $Python @lockArgs } "build_runtime_locks.py $pack (canonical)"
}
foreach ($lock in Get-ChildItem -LiteralPath $RepoLocks -Filter '*.lock') {
    $committed = Join-Path $RepoRoot "locks\$($lock.Name)"
    Assert (Test-Path -LiteralPath $committed) "нет закоммиченного лока locks\$($lock.Name) — закоммичьте файл"
    $diff = Compare-Object (Get-Content -LiteralPath $lock.FullName) (Get-Content -LiteralPath $committed)
    Assert ($null -eq $diff) "лок $($lock.Name) отличается от закоммиченного: перегенерируйте и закоммитьте"
}
Write-Host "locked: $($packs -join ', ') — совпадают с locks\"

# --- 3. локальная сводка с file://-базой -------------------------------------
Step '3. Локальная сводка (file://) и манифест'
foreach ($pack in $packs) {
    $localArgs = @('scripts\build_runtime_locks.py', '--pack', $pack, '--os', 'win',
        '--out', $LocksOut, '--url-base', $UrlBase)
    if ($pack -eq 'argos' -and $null -ne $canonicalArgosWheel) {
        $localArgs += @('--hosted-wheel', $canonicalArgosWheel.FullName)
    }
    Invoke-Checked { & $Python @localArgs } "build_runtime_locks.py $pack (local)"
}
$argosWheel = Get-ChildItem -LiteralPath $LocksOut -Filter 'argostranslate-*.whl' |
    Select-Object -First 1
Assert ($null -ne $argosWheel) 'не найдено собранное колесо argostranslate'
$releaseDir = Join-Path $ReleaseRoot "v$Version"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
Copy-Item -LiteralPath $argosWheel.FullName -Destination $releaseDir -Force
Invoke-Checked {
    & $Python 'scripts\build-runtime-manifest.py' --packs (Join-Path $LocksOut 'packs.json') `
        --out $ManifestPath --url-base $UrlBase --no-bundled
} 'build-runtime-manifest.py (local)'

# --- 4. dev-установка ---------------------------------------------------------
Step '4. dev: --deploy cpu/argos, идемпотентность, битый sha'
$oldInstall = $env:ILT_INSTALL_ROOT
$oldManifest = $env:ILT_RUNTIME_MANIFEST_URL
$devRoot = Join-Path $Stage 'root'
try {
    $env:ILT_INSTALL_ROOT = $devRoot
    $env:ILT_RUNTIME_MANIFEST_URL = Get-FileUri $ManifestPath
    Invoke-Checked { & $Python -m src.app --deploy cpu } 'dev --deploy cpu'
    Invoke-Checked { & $Python -m src.app --deploy argos } 'dev --deploy argos'
    Invoke-Checked { & $Python -m src.app --deploy cpu } 'dev --deploy cpu (повтор)'
    $importCheck = @'
import sys
root = sys.argv[1]
sys.path.insert(0, root + r'\runtime\torch-cpu\site-packages')
import torch
print('torch', torch.__version__)
sys.path.insert(0, root + r'\runtime\argos\site-packages')
import argostranslate.translate
print('argostranslate ok')
'@
    Invoke-Checked { & $Python -c $importCheck $devRoot } 'dev import torch/argostranslate'

    $corruptSnippet = @'
import json
import sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding='utf-8'))
record = next(r for r in data['packs'] if r.get('id') == 'torch-cpu')
record['files'][0]['sha256'] = '0' * 64
open(dst, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))
'@
    $corruptManifest = Join-Path $Stage 'manifest-corrupt.json'
    & $Python -c $corruptSnippet $ManifestPath $corruptManifest
    Assert ($LASTEXITCODE -eq 0) 'не удалось собрать битый манифест'
    $corruptRoot = Join-Path $Stage 'root-corrupt'
    $env:ILT_INSTALL_ROOT = $corruptRoot
    $env:ILT_RUNTIME_MANIFEST_URL = Get-FileUri $corruptManifest
    & $Python -m src.app --deploy cpu
    Assert ($LASTEXITCODE -ne 0) 'битый sha256 должен валить установку'
    $corruptRuntime = Join-Path $corruptRoot 'runtime'
    Assert (-not (Test-Path -LiteralPath (Join-Path $corruptRuntime 'torch-cpu'))) 'каталог пака не должен создаваться'
    $parts = @(Get-ChildItem -LiteralPath $corruptRuntime -Filter '*.parts' -ErrorAction SilentlyContinue)
    Assert ($parts.Count -eq 0) 'временные файлы .parts должны быть удалены'
} finally {
    $env:ILT_INSTALL_ROOT = $oldInstall
    $env:ILT_RUNTIME_MANIFEST_URL = $oldManifest
}

# --- 5. сборка и frozen-установка ---------------------------------------------
Step '5. Сборка (Flutter + PyInstaller + Inno + portable/server) и frozen-деплой'
if (-not $SkipBuild) {
    Invoke-Checked {
        & (Join-Path $RepoRoot 'scripts\build-windows.ps1') -SkipModels `
            -BuildPython $BuildPython -Portable -ServerZip
    } 'build-windows.ps1 -SkipModels -Portable -ServerZip'
}
$portableZip = Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'dist') -Filter '*-portable.zip' |
    Sort-Object Name | Select-Object -Last 1
Assert ($null -ne $portableZip) 'нет portable zip в dist (соберите без -SkipBuild)'
$portableRoot = Join-Path $Stage 'portable'
$portableApp = Join-Path $portableRoot 'ImageLocalizationTool'
if (-not (Test-Path -LiteralPath $portableApp)) {
    New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($portableZip.FullName, $portableRoot)
}
$sidecar = Join-Path $portableApp 'sidecar\ImageLocalizationTool.exe'
Assert (Test-Path -LiteralPath $sidecar) "нет sidecar exe: $sidecar"
try {
    $env:ILT_INSTALL_ROOT = $portableApp
    $env:ILT_RUNTIME_MANIFEST_URL = Get-FileUri $ManifestPath
    Invoke-FrozenDeploy -Exe $sidecar -Target 'cpu' -Label 'frozen portable --deploy cpu'
    Invoke-FrozenDeploy -Exe $sidecar -Target 'cpu' -Label 'frozen portable --deploy cpu (повтор)'
    $marker = Join-Path $portableApp 'runtime\torch-cpu\pack.json'
    Assert (Test-Path -LiteralPath $marker) 'портативный runtime\torch-cpu\pack.json не создан'
    $frozenCheck = "import sys; sys.path.insert(0, sys.argv[1] + r'\runtime\torch-cpu\site-packages'); import torch; print('portable torch', torch.__version__)"
    Invoke-Checked { & $Python -c $frozenCheck $portableApp } 'импорт torch из портативного пака'
} finally {
    $env:ILT_INSTALL_ROOT = $oldInstall
    $env:ILT_RUNTIME_MANIFEST_URL = $oldManifest
}

# --- 6. dry-run публикации ------------------------------------------------------
Step '6. publish-release -DryRun (git/gh не трогаются)'
Invoke-Checked { & $Python (Join-Path $RepoRoot 'scripts\build-extension.py') } 'build-extension.py'
Invoke-Checked { & (Join-Path $RepoRoot 'scripts\publish-release.ps1') -DryRun } 'publish-release -DryRun'

# --- 7. гейт --------------------------------------------------------------------
Step '7. check_release --deep (Tier 1 HEAD + Tier 2 install/import)'
Invoke-Checked {
    & $Python 'scripts\check_release.py' --manifest $ManifestPath --assets dist --deep
} 'check_release.py --deep'

if (-not $KeepStages) {
    Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "E2E приёмка пройдена: лок-сводки, dev/frozen установка, dry-run публикации и гейт зелёные." -ForegroundColor Green
