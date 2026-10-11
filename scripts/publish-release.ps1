#Requires -Version 5.1
<#
.SYNOPSIS
  Publish the release: Windows assets first, then finalize after CI.

.DESCRIPTION
  Phase Windows (local):
    1. check local assets (setup, portable zip, server zip, packs, extensions);
    2. rebuild release runtime manifest from dist/packs/packs.json;
    3. write dist/SHA256SUMS-windows.txt;
    4. with -ResetTag delete the old release/tag; with -PushTag push the fresh tag;
    5. create a draft release and upload assets.

  Phase Final (after the Linux CI run):
    1. download packs-linux.json and SHA256SUMS-linux.txt from the release;
    2. merge pack records and rebuild the manifest (bundled copy untouched);
    3. write the combined dist/SHA256SUMS.txt and upload it with the manifest;
    4. with -Publish mark the release as published.

  Phases are idempotent: uploads use --clobber.

.EXAMPLE
  .\scripts\publish-release.ps1 -DryRun
  .\scripts\publish-release.ps1 -ResetTag -PushTag
  .\scripts\publish-release.ps1 -Phase Final -Publish
#>
param(
    [ValidateSet('Windows', 'Final')]
    [string] $Phase = 'Windows',
    [switch] $ResetTag,
    [switch] $PushTag,
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
        # stderr нативных команд гасим: иначе PS5.1 с EAP=Stop падает на пустом выводе.
        & gh release delete $tag --yes --cleanup-tag 2>&1 | Out-Null
        & git tag -d $tag 2>&1 | Out-Null
        & git push origin ":refs/tags/$tag" 2>&1 | Out-Null
    }
    if ($PushTag) {
        Invoke-Checked { & git tag -f $tag } "git tag -f $tag"
        Invoke-Checked { & git push -f origin $tag } "git push $tag"
    }

    $releaseExists = $false
    & gh release view $tag 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $releaseExists = $true }
    if (-not $releaseExists) {
        Invoke-Checked {
            & gh release create $tag --draft --title $version --notes-file $notes
        } "gh release create $tag"
    }
    Invoke-Checked {
        & gh release upload $tag @assets --clobber
    } "gh release upload $tag (Windows assets)"
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
    $merged = [System.Collections.Generic.List[object]]::new()
    $seen = @{}
    foreach ($file in @($winSummary, $linuxSummary)) {
        $items = @(Get-Content -LiteralPath $file -Raw | ConvertFrom-Json)
        foreach ($item in $items) {
            $key = "$($item.id)/$($item.os)"
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $merged.Add($item)
        }
    }
    $mergedPath = Join-Path $tmp 'packs-all.json'
    $merged | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $mergedPath -Encoding UTF8

    Invoke-Checked {
        & $python (Join-Path $RepoRoot 'scripts\build-runtime-manifest.py') `
            '--packs' $mergedPath '--out' "dist\ilt-runtime-manifest-$version.json" '--no-bundled'
    } 'build-runtime-manifest.py (merged)'

    $winLines = @(Get-Content -LiteralPath (Join-Path $RepoRoot 'dist\SHA256SUMS-windows.txt'))
    $linuxLines = @(Get-Content -LiteralPath (Join-Path $tmp 'SHA256SUMS-linux.txt'))
    $allLines = @($winLines + $linuxLines | Sort-Object)
    $sumPath = Join-Path $RepoRoot 'dist\SHA256SUMS.txt'
    $allLines | Set-Content -LiteralPath $sumPath -Encoding ASCII
    Write-Host "==> SHA256SUMS.txt ($($allLines.Count) files)"

    $manifest = Join-Path $RepoRoot "dist\ilt-runtime-manifest-$version.json"
    if ($DryRun) {
        Write-Host "Dry run: manifest $manifest and sums are ready, gh untouched."
        return
    }
    Invoke-Checked {
        & gh release upload $tag $manifest $sumPath --clobber
    } "gh release upload $tag (manifest + sums)"
    if ($Publish) {
        Invoke-Checked {
            & gh release edit $tag --draft=false
        } "gh release edit $tag --draft=false"
        Write-Host "Release published: $tag" -ForegroundColor Green
    } else {
        Write-Host 'Final phase done. Re-run with -Publish to publish the release.'
    }
}
