#Requires -Version 5.1
[CmdletBinding(DefaultParameterSetName = 'Prepare')]
param(
    [Parameter(ParameterSetName = 'Prepare', Mandatory = $true)] [switch] $Prepare,
    [Parameter(ParameterSetName = 'Publish', Mandatory = $true)] [switch] $Publish,
    [switch] $DryRun,
    [switch] $SmokePassed,
    [string] $Tag = '',
    [string] $Python = '',
    [string] $BuildPython = '',
    [switch] $SkipBuild
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
if (-not $Python) { $Python = Join-Path $RepoRoot 'venv\Scripts\python.exe' }
if (-not $BuildPython) { $BuildPython = Join-Path $RepoRoot 'venv-release\Scripts\python.exe' }
function Checked {
    param([scriptblock] $Action, [string] $Label)
    Write-Host "==> $Label"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Label failed ($LASTEXITCODE)" }
}
$version = (& $Python -c 'from scripts.smoke_dist import read_app_version; print(read_app_version())').Trim()
if (-not $Tag) { $Tag = "v$version" }
$manifest = "dist\ilt-runtime-manifest-$version.json"
$components = "dist\ilt-component-manifest-$version.json"
if ($DryRun) {
    Checked { & $Python 'scripts\build-runtime-manifest.py' } 'validate fixed catalog'
    Copy-Item -LiteralPath 'src\app\component_manifest.json' -Destination $components -Force
    Write-Host 'Prepare: fixed catalogs -> Windows/tests/extensions -> Linux CI -> immutable candidate -> draft'
    Write-Host 'Publish: manual smoke -> verify exact candidate -> anonymous dependency check -> publish draft'
    Write-Host 'Dry run: no GitHub changes, no dependency resolution, no application builds.'
    exit 0
}
if ($Prepare) {
    Checked { & $Python 'scripts\build-runtime-manifest.py' } 'final catalogs before packaging'
    Copy-Item -LiteralPath 'src\app\component_manifest.json' -Destination $components -Force
    Checked { & $Python 'scripts\check_release.py' --manifest $manifest --components $components --anonymous } 'anonymous dependency gate'
    Checked { & $Python -m pytest -q } 'Python tests'
    $flutter = Join-Path $env:LOCALAPPDATA 'flutter\bin\flutter.bat'
    Push-Location 'apps\desktop'
    try {
        Checked { & $flutter analyze } 'Flutter analyze'
        Checked { & $flutter test } 'Flutter tests'
    } finally { Pop-Location }
    if (-not $SkipBuild) {
        Checked { & 'scripts\build-windows.ps1' -SkipModels -Portable -ServerZip -BuildPython $BuildPython } 'Windows base'
    }
    Checked { & $Python 'scripts\build-extension.py' } 'browser extensions'
    $dirty = (& git status --porcelain --untracked-files=all | Where-Object { $_ -notlike '?? .agents/*' } | Out-String).Trim()
    if ($dirty) { throw 'Commit the prepared source/catalog before triggering Linux CI; ordinary releases do not rewrite locks.' }
    $commit = (& git rev-parse HEAD).Trim()
    $branch = (& git branch --show-current).Trim()
    Checked { & git push origin $branch } 'push release source'
    $existing = & gh release view $Tag --json isDraft --jq '.isDraft' 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing -eq 'false') { throw 'This release is already public; use a new version.' }
    if ($LASTEXITCODE -ne 0) {
        Checked { & gh release create $Tag --draft --target $commit --title $version --notes-file "docs\RELEASE_NOTES_$version.md" } 'create draft'
    }
    $dispatchTime = (Get-Date).ToUniversalTime().AddSeconds(-2)
    Checked { & gh workflow run 'release.yml' --ref $branch -f "tag=$Tag" -f "source_ref=$commit" } 'Linux CI from exact source'
    $runId = ''
    for ($attempt = 0; $attempt -lt 20 -and -not $runId; $attempt++) {
        Start-Sleep -Seconds 3
        $runs = & gh run list --workflow release.yml --branch $branch --event workflow_dispatch --limit 10 --json databaseId,headSha,status,createdAt | ConvertFrom-Json
        $match = @($runs | Where-Object { $_.headSha -eq $commit -and ([datetime]$_.createdAt) -ge $dispatchTime }) | Select-Object -First 1
        if ($match) { $runId = $match.databaseId }
    }
    if (-not $runId) { throw 'Linux CI was dispatched; rerun after checking its status.' }
    Checked { & gh run watch $runId --exit-status } 'wait for Linux'
    Checked { & gh release download $Tag -p "ImageLocalizationTool-$version-server-linux-x64.tar.gz" --dir dist --clobber } 'collect Linux artifact'
    Checked { & $Python 'scripts\smoke-components.py' --portable "dist\ImageLocalizationTool-$version-windows-x64-portable.zip" } 'frozen component smoke'
    Checked { & $Python 'scripts\release_candidate.py' create --tag $Tag --checks-passed } 'record exact candidate'
    $report = Get-Content 'build\release-candidate.json' -Raw | ConvertFrom-Json
    foreach ($asset in $report.assets) {
        Checked { & gh release upload $Tag (Join-Path 'dist' $asset.name) --clobber } "draft $($asset.name)"
    }
    Checked { & gh release upload $Tag 'dist\SHA256SUMS.txt' --clobber } 'candidate checksums'
    Write-Host 'Candidate prepared. Run manual smoke, then release.ps1 -Publish -SmokePassed.'
    exit 0
}
if ($SmokePassed) {
    Checked { & $Python 'scripts\release_candidate.py' approve } 'record manual smoke acknowledgement'
}
Checked { & $Python 'scripts\release_candidate.py' verify } 'verify same candidate bytes'
$report = Get-Content 'build\release-candidate.json' -Raw | ConvertFrom-Json
if ($report.tag -ne $Tag) { throw 'Tag does not match the prepared candidate.' }
Checked { & $Python 'scripts\check_release.py' --manifest $manifest --components $components --anonymous } 'anonymous dependency gate'
$verifyDir = Join-Path $RepoRoot 'build\release-publication-check'
New-Item -ItemType Directory -Path $verifyDir -Force | Out-Null
foreach ($asset in $report.assets) {
    Checked { & gh release download $Tag -p $asset.name --dir $verifyDir --clobber } "verify draft $($asset.name)"
    $hash = (Get-FileHash -LiteralPath (Join-Path $verifyDir $asset.name) -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $asset.sha256) { throw "Draft asset changed: $($asset.name)" }
}
Checked { & gh release edit $Tag --draft=false } 'publish approved candidate'
Write-Host 'Release published; no artifacts rebuilt.'
