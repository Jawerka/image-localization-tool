#Requires -Version 5.1
<#
.SYNOPSIS
  Sync src/web to the LAN headless host and restart ilt.service.

.EXAMPLE
  .\scripts\deploy-lan.ps1

.EXAMPLE
  .\scripts\deploy-lan.ps1 -Hosts @("192.168.88.41","192.168.88.168") -DryRun
#>
param(
    [string[]] $Hosts = @("192.168.88.41", "192.168.88.168"),
    [string] $User = "root",
    [string] $RemoteRoot = "/opt/image-localization-tool",
    [string] $Service = "ilt.service",
    [switch] $DryRun,
    [switch] $IncludeTests
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Test-SshHost {
    param([string] $Target)
    & ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "${User}@${Target}" "echo ok" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Resolve-LanHost {
    foreach ($candidate in $Hosts) {
        Write-Host "==> Probe ${User}@${candidate}"
        if ($DryRun) {
            Write-Host "    (dry-run) would probe SSH"
            return $candidate
        }
        if (Test-SshHost -Target $candidate) {
            Write-Host "    reachable"
            return $candidate
        }
        Write-Host "    unreachable"
    }
    throw "No LAN host reachable. Tried: $($Hosts -join ', ')"
}

$paths = @(
    'src',
    'web'
)
if ($IncludeTests) {
    $paths += 'tests'
}

foreach ($rel in $paths) {
    $full = Join-Path $RepoRoot $rel
    if (-not (Test-Path -LiteralPath $full)) {
        throw "Missing path to sync: $full"
    }
}

$hostName = Resolve-LanHost
$remote = "${User}@${hostName}"
$archive = Join-Path $env:TEMP ("ilt-lan-deploy-{0}.tar" -f [guid]::NewGuid().ToString('N'))

try {
    Write-Host "==> Pack $($paths -join ', ')"
    if ($DryRun) {
        Write-Host "    (dry-run) tar $($paths -join ' ')"
        Write-Host "    (dry-run) scp -> ${remote}:/tmp/ilt-deploy.tar"
        Write-Host "    (dry-run) extract under $RemoteRoot (keep venv/models/data/config)"
        Write-Host "    (dry-run) systemctl restart $Service"
        Write-Host ""
        Write-Host "LAN deploy dry-run OK against $hostName" -ForegroundColor Green
        return
    }

    & tar -cf $archive -C $RepoRoot @paths
    if ($LASTEXITCODE -ne 0) {
        throw "tar failed with exit code $LASTEXITCODE"
    }

    Write-Host "==> Upload to $remote"
    & scp -o BatchMode=yes -o ConnectTimeout=15 $archive "${remote}:/tmp/ilt-deploy.tar"
    if ($LASTEXITCODE -ne 0) {
        throw "scp failed with exit code $LASTEXITCODE"
    }

    $remoteCmd = @"
set -e
cd '$RemoteRoot'
tar -xf /tmp/ilt-deploy.tar
rm -f /tmp/ilt-deploy.tar
systemctl restart '$Service'
sleep 1
systemctl is-active '$Service'
"@
    Write-Host "==> Extract and restart $Service"
    & ssh -o BatchMode=yes -o ConnectTimeout=15 $remote $remoteCmd
    if ($LASTEXITCODE -ne 0) {
        throw "remote extract/restart failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "LAN deploy OK: ${remote}:${RemoteRoot}" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}
