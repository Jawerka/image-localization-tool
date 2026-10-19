#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Bundle,
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [ValidateRange(1, 300)] [int] $HealthTimeoutSec = 45
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-update-common.ps1')

$layout = Get-WindowsInstallLayout $InstallRoot
if (-not (Test-Path -LiteralPath $layout.Root -PathType Container)) { throw "Установка не найдена: $($layout.Root)" }
if (-not (Test-Path -LiteralPath $layout.Parent -PathType Container)) { throw "Нет папки установки: $($layout.Parent)" }
$lock = Enter-WindowsUpdateLock $layout
$stage = Join-Path $layout.Parent ".$($layout.Name).stage-$([guid]::NewGuid().ToString('N'))"
$previous = ''
$failed = ''
$movedFolders = @()
$oldMoved = $false
$activated = $false

try {
    Assert-WindowsReleaseTree $layout.Root -AllowLegacy
    $oldMetadata = Get-WindowsReleaseMetadata $layout.Root -AllowLegacy
    $legacyInstall = $oldMetadata.legacy -eq $true
    $running = Test-WindowsAppRunning $layout.Root
    if ($running) { throw "Закройте приложение перед обновлением (процесс $($running.Id))." }

    Copy-WindowsReleaseToStage $Bundle $stage
    $candidate = Get-WindowsReleaseMetadata $stage
    if ([string]$candidate.version -eq [string]$oldMetadata.version) {
        throw "Версия $($candidate.version) уже установлена."
    }
    $probe = Test-WindowsReleaseHealth $stage $HealthTimeoutSec
    if (-not $probe.Ready) { throw "Кандидат $($candidate.version) не прошёл проверку до активации: $($probe.Detail)" }
    if ($legacyInstall) {
        $legacyProbe = Test-WindowsReleaseHealth $layout.Root $HealthTimeoutSec
        if (-not $legacyProbe.Ready) { throw "Текущая установка без release.json не прошла проверку: $($legacyProbe.Detail)" }
        if ($legacyProbe.Version -notmatch '^(?:\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?|dev)$') {
            throw "Не удалось определить версию текущей установки по health API: '$($legacyProbe.Version)'"
        }
        $oldMetadata.version = $legacyProbe.Version
    }
    if ([string]$candidate.version -eq [string]$oldMetadata.version) {
        throw "Версия $($candidate.version) уже установлена."
    }

    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $previous = Join-Path $layout.Parent ".$($layout.Name).previous-$($oldMetadata.version)-$suffix"
    $failed = Join-Path $layout.Parent ".$($layout.Name).failed-$($candidate.version)-$suffix"
    Move-Item -LiteralPath $layout.Root -Destination $previous
    $oldMoved = $true
    if ($legacyInstall) { Write-WindowsReleaseMetadata $previous $oldMetadata.version }
    $movedFolders = @(Move-WindowsPersistentFolders $previous $stage)
    Move-Item -LiteralPath $stage -Destination $layout.Root
    $activated = $true

    $activeProbe = Test-WindowsReleaseHealth $layout.Root $HealthTimeoutSec
    if (-not $activeProbe.Ready) { throw "Кандидат не прошёл проверку после активации: $($activeProbe.Detail)" }
    Set-WindowsPreviousRelease $layout.Root $previous $oldMetadata.version

    Write-Host "Обновление завершено: $($oldMetadata.version) → $($candidate.version)."
    Write-Host "Предыдущая версия сохранена: $previous"
} catch {
    $failure = $_.Exception.Message
    try {
        if ($activated -and (Test-Path -LiteralPath $layout.Root -PathType Container)) {
            Restore-WindowsPersistentFolders $layout.Root $previous $movedFolders
            Move-Item -LiteralPath $layout.Root -Destination $failed
            $activated = $false
        } elseif ($movedFolders.Count -gt 0 -and (Test-Path -LiteralPath $stage -PathType Container)) {
            Restore-WindowsPersistentFolders $stage $previous $movedFolders
        }
        if ($oldMoved -and (Test-Path -LiteralPath $previous -PathType Container) -and -not (Test-Path -LiteralPath $layout.Root)) {
            Move-Item -LiteralPath $previous -Destination $layout.Root
            $oldMoved = $false
        }
    } catch {
        throw "Обновление отклонено: $failure. Автоматическое восстановление не завершилось: $($_.Exception.Message). Проверьте каталоги $previous и $stage."
    }
    throw "Обновление отклонено; восстановлена версия $($oldMetadata.version): $failure"
} finally {
    if (Test-Path -LiteralPath $stage -PathType Container) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
    Exit-WindowsUpdateLock $lock
}
