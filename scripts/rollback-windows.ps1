#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [ValidateRange(1, 300)] [int] $HealthTimeoutSec = 45
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-update-common.ps1')

$layout = Get-WindowsInstallLayout $InstallRoot
if (-not (Test-Path -LiteralPath $layout.Root -PathType Container)) { throw "Установка не найдена: $($layout.Root)" }
$lock = Enter-WindowsUpdateLock $layout
$siblings = Get-WindowsSiblingLayout $layout
$swap = $siblings.RollbackStage
$previous = $null
$currentMetadata = $null
$oldMoved = $false
$previousActivated = $false
$movedFolders = @()

try {
    $running = Test-WindowsAppRunning $layout.Root
    if ($running) { throw "Закройте приложение перед откатом (процесс $($running.Id))." }
    Assert-WindowsReleaseTree $layout.Root
    $currentMetadata = Get-WindowsReleaseMetadata $layout.Root
    $previous = Get-WindowsPreviousRelease $layout.Root

    $candidateProbe = Test-WindowsReleaseHealth $previous.Path $HealthTimeoutSec
    if (-not $candidateProbe.Ready) { throw "Предыдущая версия не прошла проверку до отката: $($candidateProbe.Detail)" }

    if ((Test-Path -LiteralPath $swap) -and (Test-Path -LiteralPath $layout.Root)) {
        Remove-WindowsDirectory $swap
    }
    Move-WindowsDirectory $layout.Root $swap
    $oldMoved = $true
    $movedFolders = @(Move-WindowsPersistentFolders $swap $previous.Path)
    Move-WindowsDirectory $previous.Path $layout.Root
    $previousActivated = $true

    $activeProbe = Test-WindowsReleaseHealth $layout.Root $HealthTimeoutSec
    if (-not $activeProbe.Ready) { throw "Предыдущая версия не прошла проверку после переключения: $($activeProbe.Detail)" }
    $saved = Promote-WindowsPreviousFolder $layout $swap
    Set-WindowsPreviousRelease $layout.Root $saved $currentMetadata.version
    Remove-WindowsDirectory $siblings.PreviousOld
    Remove-WindowsDirectory $siblings.Failed
    Remove-WindowsStaleReleaseFolders $layout @($saved)

    Write-Host "Откат завершён: $($currentMetadata.version) → $($previous.Metadata.version)."
    Write-Host "Версия $($currentMetadata.version) сохранена для повторного обновления: $saved"
} catch {
    $failure = $_.Exception.Message
    try {
        if ($previousActivated -and (Test-Path -LiteralPath $layout.Root -PathType Container)) {
            Restore-WindowsPersistentFolders $layout.Root $swap $movedFolders
            Move-WindowsDirectory $layout.Root $previous.Path
            $previousActivated = $false
        } elseif ($movedFolders.Count -gt 0 -and $previous -and (Test-Path -LiteralPath $previous.Path -PathType Container)) {
            Restore-WindowsPersistentFolders $previous.Path $swap $movedFolders
        }
        if ($oldMoved -and (Test-Path -LiteralPath $swap -PathType Container) -and -not (Test-Path -LiteralPath $layout.Root)) {
            Move-WindowsDirectory $swap $layout.Root
            $oldMoved = $false
        }
    } catch {
        $previousPath = if ($previous) { $previous.Path } else { $siblings.Previous }
        throw "Откат отклонён: $failure. Автоматическое восстановление не завершилось: $($_.Exception.Message). Проверьте каталоги $swap и $previousPath."
    }
    throw "Откат отклонён; оставлена версия $($currentMetadata.version): $failure"
} finally {
    Exit-WindowsUpdateLock $lock
}
