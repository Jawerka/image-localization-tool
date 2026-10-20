# Изолированная проверка Windows updater без изменения пользовательской установки.
[CmdletBinding()]
param(
    [string] $SourceRoot = '',
    [ValidateSet('all', 'update', 'rollback')]
    [string] $Scenario = 'all'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $SourceRoot) { $SourceRoot = Join-Path $RepoRoot 'dist\ImageLocalizationTool' }
$UpdateScript = Join-Path $RepoRoot 'scripts\update-windows.ps1'
$RollbackScript = Join-Path $RepoRoot 'scripts\rollback-windows.ps1'
$CommonScript = Join-Path $RepoRoot 'scripts\windows-update-common.ps1'
foreach ($path in @($UpdateScript, $RollbackScript, $CommonScript)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing updater file: $path" }
}
. $CommonScript
foreach ($path in @(
    (Join-Path $SourceRoot 'desktop\ImageLocalizationTool.exe'),
    (Join-Path $SourceRoot 'sidecar\ImageLocalizationTool.exe'),
    (Join-Path $SourceRoot 'web\index.html')
)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Packaged source is incomplete: $path" }
}

$Work = Join-Path ([IO.Path]::GetTempPath()) ('ilt-update-test-' + [guid]::NewGuid().ToString('N'))
$GoodBundle = Join-Path $Work 'bundle-good'
$BadBundle = Join-Path $Work 'bundle-bad'
$InstallRoot = Join-Path $Work 'ImageLocalizationTool'
$runUpdate = $Scenario -in @('all', 'update')
$runRollback = $Scenario -in @('all', 'rollback')
$timer = [Diagnostics.Stopwatch]::StartNew()
New-Item -ItemType Directory -Path $GoodBundle -Force | Out-Null
New-Item -ItemType Directory -Path $BadBundle -Force | Out-Null

function Copy-TestBundle([string] $Destination, [string] $Version, [switch] $FailHealth) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    if ($FailHealth) {
        New-Item -ItemType Directory -Path (Join-Path $Destination 'desktop'), (Join-Path $Destination 'sidecar\_internal'), (Join-Path $Destination 'web') -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\where.exe') -Destination (Join-Path $Destination 'desktop\ImageLocalizationTool.exe')
        Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\where.exe') -Destination (Join-Path $Destination 'sidecar\ImageLocalizationTool.exe')
        Set-Content -LiteralPath (Join-Path $Destination 'web\index.html') -Encoding utf8 -Value '<html></html>'
    } else {
        foreach ($folder in @('desktop', 'sidecar', 'web', 'fonts')) {
            $source = Join-Path $SourceRoot $folder
            if (Test-Path -LiteralPath $source) {
                & robocopy $source (Join-Path $Destination $folder) /E /R:1 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
                if ($LASTEXITCODE -ge 8) { throw "Could not copy test bundle folder $folder" }
            }
        }
    }
    $manifest = @{
        schema = 1
        version = $Version
        platform = 'windows-x64'
        host = 'desktop/ImageLocalizationTool.exe'
        sidecar = 'sidecar/ImageLocalizationTool.exe'
        web = 'web/index.html'
    } | ConvertTo-Json
    Set-Content -LiteralPath (Join-Path $Destination 'release.json') -Encoding utf8 -Value $manifest
}

function New-PostActivationFailureBundle([string] $Destination, [string] $Version) {
    Copy-TestBundle $Destination $Version
    $source = @'
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
public static class HealthSwitchSidecar {
    public static void Main() {
        string root = Environment.GetEnvironmentVariable("ILT_INSTALL_ROOT") ?? "";
        string data = Environment.GetEnvironmentVariable("ILT_DATA_DIR") ?? "";
        string settings = File.ReadAllText(Path.Combine(data, "settings.json"));
        Match match = Regex.Match(settings, "\\\"remote_port\\\"\\s*:\\s*(\\d+)");
        if (!match.Success) Environment.Exit(7);
        int port = Int32.Parse(match.Groups[1].Value);
        bool ready = root.IndexOf(".ImageLocalizationTool.stage-", StringComparison.OrdinalIgnoreCase) >= 0;
        TcpListener listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        try {
            using (TcpClient client = listener.AcceptTcpClient())
            using (NetworkStream stream = client.GetStream()) {
                byte[] body = Encoding.UTF8.GetBytes("{\"ready\":" + (ready ? "true" : "false") + ",\"version\":\"1.0.6\"}");
                byte[] header = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n");
                stream.Write(header, 0, header.Length);
                stream.Write(body, 0, body.Length);
            }
            if (ready) Thread.Sleep(30000);
        } finally { listener.Stop(); }
    }
}
'@
    $stub = Join-Path $Work 'health-switch-sidecar.exe'
    $sourcePath = Join-Path $Work 'health-switch-sidecar.cs'
    Set-Content -LiteralPath $sourcePath -Encoding ASCII -Value $source
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
    if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler is required for the health-switch fixture.' }
    & $compiler /nologo /target:exe "/out:$stub" $sourcePath
    if ($LASTEXITCODE -ne 0) { throw "Could not compile the health-switch sidecar fixture (csc $LASTEXITCODE)." }
    Copy-Item -LiteralPath $stub -Destination (Join-Path $Destination 'sidecar\ImageLocalizationTool.exe') -Force
    $manifest = Get-Content -LiteralPath (Join-Path $Destination 'release.json') -Raw | ConvertFrom-Json
    $manifest.version = $Version
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Destination 'release.json') -Encoding utf8
}

function Invoke-Updater([string] $ScriptPath, [string[]] $Arguments) {
    $engine = (Get-Process -Id $PID).Path
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $engine -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $output | ForEach-Object { Write-Host $_ }
    return $code
}

function Assert-Version([string] $Expected) {
    $manifest = Get-Content -LiteralPath (Join-Path $InstallRoot 'release.json') -Raw | ConvertFrom-Json
    if ($manifest.version -ne $Expected) { throw "Expected active $Expected, got $($manifest.version)" }
}

function Assert-DataUnchanged {
    foreach ($relative in $before.Keys) {
        $path = Join-Path $InstallRoot $relative.TrimStart('\')
        if (-not (Test-Path -LiteralPath $path)) { throw "Persistent file disappeared: $relative" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $before[$relative]) { throw "Persistent file changed: $relative" }
    }
}

try {
    Copy-TestBundle $GoodBundle '1.0.3'
    Copy-TestBundle $BadBundle '1.0.4' -FailHealth
    Copy-TestBundle $InstallRoot '1.0.1'
    Remove-Item -LiteralPath (Join-Path $InstallRoot 'release.json') -Force
    $legacyVersion = (Test-WindowsReleaseHealth $InstallRoot 30).Version
    if (-not $legacyVersion) { throw 'Could not read the version from the legacy installation health API' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $goodArchive = Join-Path $Work 'ImageLocalizationTool-1.0.3-windows-x64-portable.zip'
    [IO.Compression.ZipFile]::CreateFromDirectory($GoodBundle, $goodArchive, [IO.Compression.CompressionLevel]::Optimal, $true)
    foreach ($folder in @('data', 'models', 'runtime', '.resources', '.downloads', '.builtin', 'components')) {
        New-Item -ItemType Directory -Path (Join-Path $InstallRoot $folder) -Force | Out-Null
        Set-Content -LiteralPath (Join-Path (Join-Path $InstallRoot $folder) 'preserve.txt') -Encoding utf8 -Value "preserve $folder"
    }
    $keyPath = Join-Path $InstallRoot 'data\llm-api-key.txt'
    [IO.File]::WriteAllText($keyPath, 'synthetic-key', (New-Object Text.UTF8Encoding($false)))
    $before = @{}
    foreach ($leaf in @('preserve.txt', 'llm-api-key.txt')) {
        Get-ChildItem -LiteralPath $InstallRoot -Recurse -Filter $leaf | ForEach-Object {
            $before[$_.FullName.Substring($InstallRoot.Length)] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    }

    $code = Invoke-Updater $UpdateScript @('-Bundle', $goodArchive, '-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '30')
    if ($code -ne 0) { throw "Successful update returned $code" }
    Assert-Version '1.0.3'
    $pointerPath = Join-Path $Work 'ImageLocalizationTool.previous.json'
    if (-not (Test-Path -LiteralPath $pointerPath)) { throw 'Previous-release pointer was not written' }
    $pointer = Get-Content -LiteralPath $pointerPath -Raw | ConvertFrom-Json
    if ($pointer.version -ne $legacyVersion) { throw "Expected probed legacy version $legacyVersion, got $($pointer.version)" }

    Assert-DataUnchanged
    if ((Get-Content -LiteralPath $keyPath -Raw).Trim() -ne 'synthetic-key') {
        throw 'LLM key file changed during update'
    }
    $activeVersion = '1.0.3'

    if ($runRollback) {
    # Проверка после активации должна восстановить прежнюю рабочую версию.
    $postActivationBundle = Join-Path $Work 'bundle-post-activation-failure'
    New-PostActivationFailureBundle $postActivationBundle '1.0.6'
    $code = Invoke-Updater $UpdateScript @('-Bundle', $postActivationBundle, '-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
    if ($code -eq 0) { throw 'Updater unexpectedly kept a release that failed health validation after activation' }
    Assert-Version '1.0.3'
    Assert-DataUnchanged

    # Повреждённый сохранённый релиз должен блокировать откат до переключения.
    $previousRoot = Join-Path $Work $pointer.folder
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\where.exe') `
        -Destination (Join-Path $previousRoot 'sidecar\ImageLocalizationTool.exe') -Force
    $code = Invoke-Updater $RollbackScript @('-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
    if ($code -eq 0) { throw 'Rollback unexpectedly activated a release that failed health validation' }
    Assert-Version '1.0.3'
    Assert-DataUnchanged
    & robocopy (Join-Path $SourceRoot 'sidecar') (Join-Path $previousRoot 'sidecar') /E /R:1 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'Could not restore the saved release after the refusal scenario' }

    $code = Invoke-Updater $RollbackScript @('-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '30')
    if ($code -ne 0) { throw "Explicit rollback returned $code" }
    Assert-Version $legacyVersion
    Assert-DataUnchanged
    $activeVersion = $legacyVersion

    # Некорректный и выходящий за каталог указатели должны быть безопасно отклонены.
    $validPointer = Get-Content -LiteralPath $pointerPath -Raw
    try {
        Set-Content -LiteralPath $pointerPath -Encoding utf8 -Value '{bad json'
        $code = Invoke-Updater $RollbackScript @('-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
        if ($code -eq 0) { throw 'Rollback unexpectedly accepted malformed previous-release metadata' }
        Assert-Version $legacyVersion
        Assert-DataUnchanged

        $traversalPointer = @{ schema = 1; folder = '..'; version = '1.0.3' } | ConvertTo-Json
        Set-Content -LiteralPath $pointerPath -Encoding utf8 -Value $traversalPointer
        $code = Invoke-Updater $RollbackScript @('-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
        if ($code -eq 0) { throw 'Rollback unexpectedly accepted a path traversal pointer' }
        Assert-Version $legacyVersion
        Assert-DataUnchanged
    } finally {
        Set-Content -LiteralPath $pointerPath -Encoding utf8 -Value $validPointer
    }
    }

    if ($runUpdate) {
    $code = Invoke-Updater $UpdateScript @('-Bundle', $BadBundle, '-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
    if ($code -eq 0) { throw 'Candidate that cannot start unexpectedly passed health validation' }
    Assert-Version $activeVersion
    Assert-DataUnchanged

    $badMetadata = Join-Path $Work 'bundle-malformed'
    Copy-TestBundle $badMetadata '1.0.5' -FailHealth
    Set-Content -LiteralPath (Join-Path $badMetadata 'release.json') -Encoding utf8 -Value '{bad json'
    $code = Invoke-Updater $UpdateScript @('-Bundle', $badMetadata, '-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
    if ($code -eq 0) { throw 'Malformed metadata unexpectedly passed validation' }
    Assert-Version $activeVersion
    Assert-DataUnchanged

    $lockPath = Join-Path $Work '.ImageLocalizationTool.update.lock'
    $heldLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $code = Invoke-Updater $UpdateScript @('-Bundle', $GoodBundle, '-InstallRoot', $InstallRoot, '-HealthTimeoutSec', '5')
        if ($code -eq 0) { throw 'Updater unexpectedly ignored an active update lock' }
        Assert-Version $activeVersion
    } finally { $heldLock.Dispose() }

    $runningRoot = Join-Path $Work 'RunningInstall'
    Copy-TestBundle $runningRoot '1.0.1' -FailHealth
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\cmd.exe') -Destination (Join-Path $runningRoot 'sidecar\ImageLocalizationTool.exe') -Force
    $running = Start-Process -FilePath (Join-Path $runningRoot 'sidecar\ImageLocalizationTool.exe') `
        -ArgumentList @('/c', 'ping -n 15 127.0.0.1 > nul') -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Milliseconds 300
        $code = Invoke-Updater $UpdateScript @('-Bundle', $GoodBundle, '-InstallRoot', $runningRoot, '-HealthTimeoutSec', '5')
        if ($code -eq 0) { throw 'Updater unexpectedly changed a running installation' }
        $runningVersion = Get-Content -LiteralPath (Join-Path $runningRoot 'release.json') -Raw | ConvertFrom-Json
        if ($runningVersion.version -ne '1.0.1') { throw 'Running installation changed before updater refusal' }
    } finally {
        if (-not $running.HasExited) {
            & taskkill.exe /PID $running.Id /T /F 2>$null | Out-Null
            try { if (-not $running.HasExited) { $running.Kill() } } catch { }
            try { $running.WaitForExit(5000) | Out-Null } catch { }
        }
    }
    }

    $hashText = ($before.Keys | Sort-Object | ForEach-Object { "$_=$($before[$_])" }) -join "`n"
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $aggregateHash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($hashText))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
    $timer.Stop()
    Write-Host "Preserved persistent files: $($before.Count); aggregate SHA-256: $aggregateHash"
    Write-Host ("Integration elapsed: {0:N1} sec" -f $timer.Elapsed.TotalSeconds)
    Write-Host 'Windows updater integration checks passed.' -ForegroundColor Green
} finally {
    $prefix = [IO.Path]::GetFullPath($Work).TrimEnd('\') + '\'
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue)) {
        try {
            if ($process.Path -and [IO.Path]::GetFullPath($process.Path).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 250
    if (Test-Path -LiteralPath $Work) { Remove-Item -LiteralPath $Work -Recurse -Force }
}

# Expected child failures set LASTEXITCODE; make the harness result reflect
# whether its assertions completed, not the last intentionally failing child.
exit 0
