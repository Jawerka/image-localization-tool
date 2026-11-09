#Requires -Version 5.1
param(
    [string[]] $Hosts = @("192.168.88.41"),
    [string] $User = "root",
    [string] $ProxyJump = "pve.30",
    [string] $RemoteRoot = "/opt/image-localization-tool",
    [string] $Service = "ilt.service",
    [switch] $DryRun,
    [switch] $IncludeTests,
    [string] $Report = ""
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
$deployArgs = @((Join-Path $PSScriptRoot 'lan_deploy.py'), '--user', $User, '--proxy-jump', $ProxyJump, '--remote-root', $RemoteRoot, '--service', $Service)
foreach ($hostName in $Hosts) { $deployArgs += @('--host', $hostName) }
if ($DryRun) { $deployArgs += '--dry-run' }
if ($IncludeTests) { $deployArgs += '--include-tests' }
if ($Report) { $deployArgs += @('--report', $Report) }
& $Python @deployArgs
if ($LASTEXITCODE -ne 0) { throw "LAN deployment failed ($LASTEXITCODE)" }
