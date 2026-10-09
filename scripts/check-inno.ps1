#Requires -Version 5.1
<#
.SYNOPSIS
  Report whether Inno Setup (ISCC.exe) is available for installer builds.

.EXAMPLE
  .\scripts\check-inno.ps1

.EXAMPLE
  .\scripts\check-inno.ps1 -Install
#>
param(
    [switch] $Install
)

$ErrorActionPreference = 'Stop'

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

$iscc = Find-Iscc
if ($iscc) {
    Write-Host "Inno Setup found:" -ForegroundColor Green
    Write-Host "  $iscc"
    Write-Host "Installer builds: .\scripts\build-windows.ps1"
    exit 0
}

Write-Host "Inno Setup (ISCC.exe) not found." -ForegroundColor Yellow
Write-Host "Without it, use: .\scripts\build-windows.ps1 -SkipInno"
Write-Host "Install Inno Setup 6.1+: https://jrsoftware.org/isdl.php"
Write-Host "Or winget: winget install --id JRSoftware.InnoSetup -e"

if (-not $Install) {
    exit 1
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "winget not found. Install Inno Setup manually from https://jrsoftware.org/isdl.php"
}

Write-Host "==> winget install JRSoftware.InnoSetup"
& winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
if ($LASTEXITCODE -ne 0) {
    throw "winget install failed with exit code $LASTEXITCODE"
}

$iscc = Find-Iscc
if (-not $iscc) {
    throw "ISCC.exe still not found after winget install. Open a new shell or install manually."
}
Write-Host "Inno Setup ready: $iscc" -ForegroundColor Green
exit 0
