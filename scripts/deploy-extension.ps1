#Requires -Version 5.1
<#
.SYNOPSIS
  Подготовка неизменяемой сборки расширения, предпросмотр, применение и откат явного плана.
.EXAMPLE
  .\scripts\deploy-extension.ps1 -Prepare -Artifact output\extension-artifact
.EXAMPLE
  .\scripts\deploy-extension.ps1 -DryRun -Artifact output\extension-artifact -Plan output\extension-plan.json -Backup output\extension-backup
.EXAMPLE
  .\scripts\deploy-extension.ps1 -Apply -Plan output\extension-plan.json
#>
param(
    [string] $Dest = "D:\Documents\apps\extension\image-localization-tool",
    [string] $Artifact,
    [string] $Plan,
    [string] $Backup,
    [switch] $Prepare,
    [switch] $DryRun,
    [switch] $Apply,
    [switch] $Rollback,
    [switch] $SkipBuild
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$modes = @($Prepare, $DryRun, $Apply, $Rollback) | Where-Object { $_ }
if (@($modes).Count -ne 1) { throw 'Choose exactly one: -Prepare, -DryRun, -Apply, -Rollback' }
$driver = Join-Path $PSScriptRoot 'extension_deploy.py'
if ($Prepare) {
    if (-not $Artifact) { throw '-Artifact is required' }
    if (-not $SkipBuild) {
        & $Python (Join-Path $PSScriptRoot 'build-extension.py')
        if ($LASTEXITCODE -ne 0) { throw 'Extension build failed' }
    }
    & $Python $driver prepare --source (Join-Path $RepoRoot 'dist\chromium') --artifact $Artifact
} elseif ($DryRun) {
    if (-not $Artifact -or -not $Plan -or -not $Backup) { throw '-Artifact, -Plan, -Backup are required' }
    & $Python $driver dry-run --artifact $Artifact --target $Dest --plan $Plan --backup $Backup
} elseif ($Apply) {
    if (-not $Plan) { throw '-Plan is required' }
    & $Python $driver apply --plan $Plan
} else {
    if (-not $Backup) { throw '-Backup is required' }
    & $Python $driver rollback --backup $Backup
}
if ($LASTEXITCODE -ne 0) { throw "Extension operation failed: $LASTEXITCODE" }
