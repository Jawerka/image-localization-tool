#Requires -Version 5.1
param(
    [string] $Dest = "D:\Documents\apps\ImageLocalizationTool",
    [switch] $Build,
    [switch] $IncludeModels,
    [switch] $DryRun
)
$ErrorActionPreference = 'Stop'
function Get-DeployHash([string] $Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','') }
    finally { $hash.Dispose(); $stream.Dispose() }
}
$RepoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DistDir = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'dist\ImageLocalizationTool'))
$Dest = [IO.Path]::GetFullPath($Dest).TrimEnd('\')
if ($Dest -eq [IO.Path]::GetPathRoot($Dest).TrimEnd('\') -or $Dest -eq $RepoRoot -or $Dest -eq $DistDir -or $RepoRoot.StartsWith($Dest + '\',[StringComparison]::OrdinalIgnoreCase) -or $Dest.StartsWith($DistDir + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe deployment target' }
foreach ($startPath in @($DistDir,$Dest)) {
    $currentPath = $startPath
    while ($currentPath) {
        if ((Test-Path -LiteralPath $currentPath) -and ((Get-Item -LiteralPath $currentPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Reparse point not allowed: $currentPath" }
        $currentPath = [IO.Path]::GetDirectoryName($currentPath)
    }
}
if ($Build) {
    if ($DryRun) { throw 'Build first, then run -DryRun against the actual artifacts' }
    $buildArgs = @{}
    if (-not $IncludeModels) { $buildArgs['SkipModels'] = $true }
    & (Join-Path $PSScriptRoot 'build-windows.ps1') @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
}
foreach ($required in @('desktop\ImageLocalizationTool.exe','sidecar\ImageLocalizationTool.exe','web\index.html')) {
    if (-not (Test-Path -LiteralPath (Join-Path $DistDir $required) -PathType Leaf)) { throw "Missing build artifact: $required" }
}
$managed = @('desktop','sidecar','web','fonts')
if ($IncludeModels) { $managed += 'models' }
$targets = @()
foreach ($name in $managed) {
    $source = Join-Path $DistDir $name
    $target = Join-Path $Dest $name
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { continue }
    foreach ($checkRoot in @($source,$target,$Dest)) {
        if (Test-Path -LiteralPath $checkRoot) {
            if ((Get-Item -LiteralPath $checkRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point not allowed: $checkRoot" }
        }
    }
    foreach ($checkRoot in @($source,$target)) {
        if (Test-Path -LiteralPath $checkRoot) {
            $link = Get-ChildItem -LiteralPath $checkRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1
            if ($link) { throw "Reparse point not allowed: $($link.FullName)" }
        }
    }
    $copyMode = if ($name -eq 'models') { '/E' } else { '/MIR' }
    $targets += [pscustomobject]@{ Source=$source; Target=$target; Mode=$copyMode }
}
Write-Host '==> DRY RUN (managed code directories only; data/runtime/resources are outside scope)'
foreach ($entry in $targets) {
    & robocopy $entry.Source $entry.Target $entry.Mode /L /XJ /R:0 /W:0 /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Dry run failed: $($entry.Target)" }
}
if ($DryRun) { Write-Host 'Windows deploy dry-run OK'; return }
$backupRoot = Join-Path (Split-Path -Parent $Dest) ('.' + (Split-Path -Leaf $Dest) + '.backup-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $Dest) {
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    foreach ($name in @('desktop','sidecar','web','fonts','data')) {
        $source = Join-Path $Dest $name
        if (Test-Path -LiteralPath $source) {
            $sourceFiles = @(Get-ChildItem -LiteralPath $source -Recurse -File -Force)
            & robocopy $source (Join-Path $backupRoot $name) /E /COPY:DATS /XJ /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "Backup failed: $name" }
            foreach ($sourceFile in $sourceFiles) {
                $relative = $sourceFile.FullName.Substring($source.Length).TrimStart('\')
                $savedFile = Join-Path (Join-Path $backupRoot $name) $relative
                if (-not (Test-Path -LiteralPath $savedFile -PathType Leaf)) { throw "Backup file missing: $name\$relative" }
                if ((Get-DeployHash $sourceFile.FullName) -ne (Get-DeployHash $savedFile)) { throw "Backup hash mismatch: $name\$relative" }
            }
        }
    }
    Write-Host "Backup: $backupRoot"
}
foreach ($entry in $targets) {
    & robocopy $entry.Source $entry.Target $entry.Mode /XJ /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copy failed: $($entry.Target); backup: $backupRoot" }
}
$release = Join-Path $DistDir 'release.json'
if (Test-Path -LiteralPath $release) { Copy-Item -LiteralPath $release -Destination (Join-Path $Dest 'release.json') -Force }
Write-Host 'Windows deploy OK:'
Write-Host (Join-Path $Dest 'desktop\ImageLocalizationTool.exe')
