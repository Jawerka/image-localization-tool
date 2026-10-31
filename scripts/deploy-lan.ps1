#Requires -Version 5.1
<#
.SYNOPSIS
  Sync src/web to the LAN headless host and restart ilt.service.

.EXAMPLE
  .\scripts\deploy-lan.ps1

.EXAMPLE
  .\scripts\deploy-lan.ps1 -Hosts @("192.168.88.41") -ProxyJump pve.30 -DryRun
#>
param(
    [string[]] $Hosts = @("192.168.88.41"),
    [string] $User = "root",
    [string] $ProxyJump = "pve.30",
    [string] $RemoteRoot = "/opt/image-localization-tool",
    [string] $Service = "ilt.service",
    [switch] $DryRun,
    [switch] $IncludeTests
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$sshOptions = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'StrictHostKeyChecking=accept-new')
if (-not [string]::IsNullOrWhiteSpace($ProxyJump)) {
    $sshOptions += @('-J', $ProxyJump)
}

function Test-SshHost {
    param([string] $Target)
    & ssh @sshOptions "${User}@${Target}" "echo ok" 2>$null
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
    & scp @sshOptions $archive "${remote}:/tmp/ilt-deploy.tar"
    if ($LASTEXITCODE -ne 0) {
        throw "scp failed with exit code $LASTEXITCODE"
    }

    # LF-only: Windows CRLF breaks remote bash ("set: - : invalid option").
    $remoteCmd = @(
        'set -e'
        "cd '$RemoteRoot'"
        'tar -xf /tmp/ilt-deploy.tar'
        'rm -f /tmp/ilt-deploy.tar'
        "systemctl restart '$Service'"
        'ready=0'
        'for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do'
        '  body=$(curl -fsS --max-time 3 http://127.0.0.1:8765/v1/health 2>/dev/null) || { sleep 1; continue; }'
        '  case "$body" in'
        '    *\"ready\":true*|*\"ready\": true*) ready=1; break ;;'
        '  esac'
        '  sleep 1'
        'done'
        'test "$ready" = 1'
        "systemctl is-active '$Service'"
    ) -join "`n"
    Write-Host "==> Extract and restart $Service"
    $remoteOut = & ssh @sshOptions $remote $remoteCmd 2>&1
    Write-Host $remoteOut
    if ($LASTEXITCODE -ne 0) {
        throw "remote extract/restart failed with exit code $LASTEXITCODE"
    }
    if (("$remoteOut") -notmatch '(?m)^active\s*$') {
        throw "remote service not active after deploy: $remoteOut"
    }

    Write-Host ""
    Write-Host "LAN deploy OK: ${remote}:${RemoteRoot}" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}
