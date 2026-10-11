#Requires -Version 5.1
<#
.SYNOPSIS
  Publish the release: Windows assets first, then finalize after CI.

.DESCRIPTION
  Phase Windows (local):
    1. check local assets (setup, portable zip, server zip, packs, extensions);
    2. rebuild release runtime manifest from dist/packs/packs.json;
    3. write dist/SHA256SUMS-windows.txt;
    4. with -ResetTag delete the old release, its tag and assets;
       with -PushTag push the fresh tag;
    5. create a draft release and upload the missing assets one file at a time.

  Phase Final (after the Linux CI run):
    1. download packs-linux.json and SHA256SUMS-linux.txt from the release;
    2. merge pack records and rebuild the manifest (bundled copy untouched);
    3. write the combined dist/SHA256SUMS.txt, replace the release manifest
       and upload the sums;
    4. with -Publish mark the release as published.

  Uploads are per file: an asset already on the release with the same sha256
  digest is skipped, a differing one is only overwritten with -Replace
  (--clobber deletes the existing asset before the new upload starts, so a
  failed replacement loses it). Final rewrites the manifest on purpose: the
  Windows phase uploads a Windows-only manifest first.

.EXAMPLE
  .\scripts\publish-release.ps1 -DryRun
  .\scripts\publish-release.ps1 -PushTag
  .\scripts\publish-release.ps1 -Phase Final -Publish
#>
param(
    [ValidateSet('Windows', 'Final')]
    [string] $Phase = 'Windows',
    [switch] $ResetTag,
    [switch] $PushTag,
    [switch] $Replace,
    [switch] $Publish,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Label)
    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Quiet {
    # Run a native command swallowing stderr; returns $LASTEXITCODE.
    # PS 5.1 turns native stderr into a terminating error under EAP=Stop, so the
    # caller lowers EAP for the duration of the call (gh release view/delete log
    # to stderr even when the outcome is expected).
    param([scriptblock]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command 2>&1 | Out-Null
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Get-ReleaseAssetMap {
    # name -> sha256 digest; empty when the release does not exist yet.
    param([string]$Tag)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = & gh release view $Tag --json assets 2>$null
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        return @{}
    }
    $map = @{}
    foreach ($asset in @((($raw -join "`n") | ConvertFrom-Json).assets)) {
        if ($asset.name) {
            $map[[string]$asset.name] = [string]$asset.digest
        }
    }
    return $map
}

function Send-ReleaseAssets {
    # Upload files one by one, skipping assets that are already present with
    # the same digest. -Replace allows overwriting differing assets.
    param(
        [string]$Tag,
        [string[]]$Paths,
        [hashtable]$Existing,
        [switch]$Replace
    )
    foreach ($path in $Paths) {
        $name = Split-Path -Leaf $path
        $localHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
        if (-not $Existing.ContainsKey($name)) {
            Invoke-Checked { & gh release upload $Tag $path } "gh release upload $name"
            continue
        }
        if ($Existing[$name] -eq "sha256:$localHash") {
            Write-Host "==> skip $name (already on the release)"
            continue
        }
        if (-not $Replace) {
            Write-Host "==> skip $name (release copy differs; pass -Replace to overwrite)"
            continue
        }
        Invoke-Checked { & gh release upload $Tag $path --clobber } "gh release upload $name"
    }
}

function Get-AppVersion {
    $text = Get-Content -LiteralPath (Join-Path $RepoRoot 'src\app\__init__.py') -Raw
    $match = [regex]::Match($text, "__version__\s*=\s*['""]([^'""]+)['""]")
    if (-not $match.Success) {
        throw '__version__ not found in src\app\__init__.py'
    }
    return $match.Groups[1].Value
}

function Get-Sha256Line {
    param([string]$Path)
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
    return ('{0}  {1}' -f $hash, (Split-Path -Leaf $Path))
}

function Resolve-BuildPython {
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) { return $venvPy }
    $releasePy = Join-Path $RepoRoot 'venv-release\Scripts\python.exe'
    if (Test-Path -LiteralPath $releasePy) { return $releasePy }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw 'python.exe not found.'
}

function Get-NotesFile {
    param([string]$Version)
    $versioned = Join-Path $RepoRoot "docs\RELEASE_NOTES_$Version.md"
    if (Test-Path -LiteralPath $versioned) { return $versioned }
    $plain = Join-Path $RepoRoot 'docs\RELEASE_NOTES.md'
    if (Test-Path -LiteralPath $plain) { return $plain }
    throw "No release notes: expected $versioned"
}

$version = Get-AppVersion
$tag = "v$version"
$notes = Get-NotesFile -Version $version
$python = Resolve-BuildPython

if ($Phase -eq 'Windows') {
    $setup = Join-Path $RepoRoot "dist\ImageLocalizationTool-$version-windows-x64-setup.exe"
    $portable = Join-Path $RepoRoot "dist\ImageLocalizationTool-$version-windows-x64-portable.zip"
    $serverZip = Join-Path $RepoRoot "dist\ImageLocalizationTool-$version-server-win64.zip"
    foreach ($path in @($setup, $portable, $serverZip)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Missing asset: $path. Build it first (build-windows.ps1, package-portable.ps1, package-server.ps1)."
        }
    }
    $packs = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'dist\packs') -Filter '*.7z' | Sort-Object Name)
    if ($packs.Count -eq 0) {
        throw 'No runtime packs in dist\packs. Run scripts\build-runtime-packs.ps1.'
    }
    $extensions = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'dist') -Filter 'ilt-extension-*.zip' | Sort-Object Name)
    if ($extensions.Count -eq 0) {
        throw 'No extension zips. Run python scripts\build-extension.py.'
    }

    Invoke-Checked {
        & $python (Join-Path $RepoRoot 'scripts\build-runtime-manifest.py') `
            '--out' "dist\ilt-runtime-manifest-$version.json" '--no-bundled'
    } 'build-runtime-manifest.py'

    $manifest = Join-Path $RepoRoot "dist\ilt-runtime-manifest-$version.json"
    $assets = @($setup, $portable, $serverZip, $manifest) + $packs.FullName + $extensions.FullName
    $sumLines = @($assets | ForEach-Object { Get-Sha256Line -Path $_ })
    $sumPath = Join-Path $RepoRoot 'dist\SHA256SUMS-windows.txt'
    $sumLines | Set-Content -LiteralPath $sumPath -Encoding ASCII
    Write-Host "==> SHA256SUMS-windows.txt ($($sumLines.Count) files)"

    if ($DryRun) {
        Write-Host 'Dry run: git/gh untouched. Assets:'
        $assets | ForEach-Object { Write-Host "  $_" }
        return
    }

    if ($ResetTag) {
        Write-Host "==> ResetTag $tag"
        Invoke-Quiet { & gh release delete $tag --yes --cleanup-tag } | Out-Null
        Invoke-Quiet { & git tag -d $tag } | Out-Null
        Invoke-Quiet { & git push origin ":refs/tags/$tag" } | Out-Null
    }
    if ($PushTag) {
        Invoke-Checked { & git tag -f $tag } "git tag -f $tag"
        Invoke-Checked { & git push -f origin $tag } "git push $tag"
    }

    $releaseExists = (Invoke-Quiet { & gh release view $tag }) -eq 0
    if (-not $releaseExists) {
        Invoke-Checked {
            & gh release create $tag --draft --title $version --notes-file $notes
        } "gh release create $tag"
    }
    $existing = Get-ReleaseAssetMap -Tag $tag
    Send-ReleaseAssets -Tag $tag -Paths $assets -Existing $existing -Replace:$Replace
    Write-Host "Windows phase done: draft $tag" -ForegroundColor Green
    if (-not $Publish) {
        Write-Host 'Next: wait for the Linux CI, then run -Phase Final -Publish.'
    }
}

if ($Phase -eq 'Final') {
    $tmp = Join-Path $RepoRoot "build\release-$tag"
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null

    Invoke-Checked {
        & gh release download $tag -p 'packs-linux.json' -p 'SHA256SUMS-linux.txt' --dir $tmp --clobber
    } "download Linux metadata ($tag)"

    $winSummary = Join-Path $RepoRoot 'dist\packs\packs.json'
    $linuxSummary = Join-Path $tmp 'packs-linux.json'
    if (-not (Test-Path -LiteralPath $linuxSummary)) {
        throw "No Linux pack summary: $linuxSummary. Did the CI finish?"
    }
    # Python merges the summaries by (id, os); a later --packs wins.
    Invoke-Checked {
        & $python (Join-Path $RepoRoot 'scripts\build-runtime-manifest.py') `
            '--packs' $winSummary '--packs' $linuxSummary `
            '--out' "dist\ilt-runtime-manifest-$version.json" '--no-bundled'
    } 'build-runtime-manifest.py (merged)'

    $manifest = Join-Path $RepoRoot "dist\ilt-runtime-manifest-$version.json"
    # This phase rebuilds the manifest, so its checksum line must be fresh;
    # the Windows list still carries the win-only manifest hash.
    $winLines = @(Get-Content -LiteralPath (Join-Path $RepoRoot 'dist\SHA256SUMS-windows.txt') |
        Where-Object { $_ -notmatch 'ilt-runtime-manifest-.*\.json$' })
    $linuxLines = @(Get-Content -LiteralPath (Join-Path $tmp 'SHA256SUMS-linux.txt'))
    $manifestLine = Get-Sha256Line -Path $manifest
    $allLines = @($winLines + $linuxLines + $manifestLine | Sort-Object)
    $sumPath = Join-Path $RepoRoot 'dist\SHA256SUMS.txt'
    $allLines | Set-Content -LiteralPath $sumPath -Encoding ASCII
    Write-Host "==> SHA256SUMS.txt ($($allLines.Count) files)"
    if ($DryRun) {
        Write-Host "Dry run: manifest $manifest and sums are ready, gh untouched."
        return
    }
    # This phase rebuilds the manifest: the merged copy must replace the
    # Windows-only one uploaded earlier, so the metadata allows --clobber.
    $existing = Get-ReleaseAssetMap -Tag $tag
    Send-ReleaseAssets -Tag $tag -Paths @($manifest, $sumPath) -Existing $existing -Replace
    if ($Publish) {
        Invoke-Checked {
            & gh release edit $tag --draft=false
        } "gh release edit $tag --draft=false"
        Write-Host "Release published: $tag" -ForegroundColor Green
    } else {
        Write-Host 'Final phase done. Re-run with -Publish to publish the release.'
    }
}
