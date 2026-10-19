# Общие проверки, staging и health probe для Windows update/rollback.

$script:WindowsPersistentFolders = @(
    'data', 'models', 'runtime', '.resources', '.downloads', '.builtin', 'components'
)

function Get-WindowsInstallLayout([string] $InstallRoot) {
    $root = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
    if (-not [IO.Path]::IsPathRooted($root) -or $root -match '^[A-Za-z]:$') {
        throw 'Корень установки должен быть абсолютным каталогом, отличным от корня диска.'
    }
    $parent = Split-Path -Parent $root
    $name = Split-Path -Leaf $root
    if (-not $parent -or -not $name) { throw 'Некорректный корень установки.' }
    [pscustomobject]@{
        Root = $root
        Parent = [IO.Path]::GetFullPath($parent)
        Name = $name
        Lock = Join-Path $parent ".$name.update.lock"
        PreviousPointer = Join-Path $parent "$name.previous.json"
    }
}

function Enter-WindowsUpdateLock($Layout) {
    try {
        $stream = [IO.File]::Open(
            $Layout.Lock,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
        $stream.SetLength(0)
        $bytes = [Text.Encoding]::UTF8.GetBytes("$PID`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return $stream
    } catch [IO.IOException] {
        throw 'Другая операция обновления или отката уже выполняется.'
    }
}

function Exit-WindowsUpdateLock($Stream) {
    if ($null -ne $Stream) { $Stream.Dispose() }
}

function Get-WindowsReleaseMetadata([string] $ReleaseRoot, [switch] $AllowLegacy) {
    $path = Join-Path $ReleaseRoot 'release.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        if (-not $AllowLegacy) { throw "В пакете нет release.json: $ReleaseRoot" }
        $legacyEntries = @(
            'desktop\ImageLocalizationTool.exe',
            'sidecar\ImageLocalizationTool.exe',
            'web\index.html'
        )
        foreach ($relative in $legacyEntries) {
            $entry = Join-Path $ReleaseRoot $relative
            if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "В старой установке отсутствует обязательный файл: $relative" }
            $entryItem = Get-Item -LiteralPath $entry -Force
            if (($entryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Файл старой установки не может быть ссылкой: $relative" }
        }
        $internal = Join-Path $ReleaseRoot 'sidecar\_internal'
        if (-not (Test-Path -LiteralPath $internal -PathType Container)) { throw 'В старой установке отсутствует sidecar\_internal.' }
        $internalItem = Get-Item -LiteralPath $internal -Force
        if (($internalItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'sidecar\_internal не может быть ссылкой.' }
        return [pscustomobject]@{ schema = 0; version = ''; platform = 'windows-x64'; legacy = $true }
    }
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'release.json не может быть ссылкой.' }
    try {
        $metadata = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Не удалось прочитать release.json: $($_.Exception.Message)"
    }
    if ($metadata.schema -ne 1) { throw 'Неподдерживаемая схема release.json.' }
    if ($metadata.platform -ne 'windows-x64') { throw 'Пакет не предназначен для Windows x64.' }
    if ([string]$metadata.version -notmatch '^(?:\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?|dev)$') { throw 'В release.json указана некорректная версия.' }
    $expected = @{
        host = 'desktop/ImageLocalizationTool.exe'
        sidecar = 'sidecar/ImageLocalizationTool.exe'
        web = 'web/index.html'
    }
    foreach ($key in $expected.Keys) {
        if ([string]$metadata.$key -ne $expected[$key]) { throw "Некорректный путь '$key' в release.json." }
        $relative = $expected[$key].Replace('/', '\')
        $entry = Join-Path $ReleaseRoot $relative
        if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "В пакете отсутствует обязательный файл: $relative" }
        $entryItem = Get-Item -LiteralPath $entry -Force
        if (($entryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Обязательный файл не может быть ссылкой: $relative" }
    }
    $internal = Join-Path $ReleaseRoot 'sidecar\_internal'
    if (-not (Test-Path -LiteralPath $internal -PathType Container)) { throw 'В пакете отсутствует sidecar\_internal.' }
    $internalItem = Get-Item -LiteralPath $internal -Force
    if (($internalItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'sidecar\_internal не может быть ссылкой.' }
    return $metadata
}

function Assert-WindowsReleaseTree([string] $ReleaseRoot, [switch] $AllowLegacy) {
    $rootItem = Get-Item -LiteralPath $ReleaseRoot -Force
    if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Каталог релиза не может быть ссылкой.' }
    Get-WindowsReleaseMetadata $ReleaseRoot -AllowLegacy:$AllowLegacy | Out-Null
}

function Write-WindowsReleaseMetadata([string] $ReleaseRoot, [string] $Version) {
    $metadata = [ordered]@{
        schema = 1
        version = $Version
        platform = 'windows-x64'
        host = 'desktop/ImageLocalizationTool.exe'
        sidecar = 'sidecar/ImageLocalizationTool.exe'
        web = 'web/index.html'
    } | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath (Join-Path $ReleaseRoot 'release.json') -Encoding UTF8 -Value $metadata
}

function Copy-WindowsReleaseToStage([string] $Bundle, [string] $Stage) {
    if (-not (Test-Path -LiteralPath $Bundle)) { throw "Не найден пакет обновления: $Bundle" }
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null
    if (Test-Path -LiteralPath $Bundle -PathType Container) {
        $arguments = @(
            $Bundle, $Stage, '/E', '/COPY:DAT', '/DCOPY:DAT', '/XJ', '/R:1', '/W:1',
            '/NFL', '/NDL', '/NJH', '/NJS', '/nc', '/ns', '/np'
        )
        & robocopy @arguments | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Не удалось скопировать пакет (robocopy $LASTEXITCODE)." }
    } elseif ([IO.Path]::GetExtension($Bundle).ToLowerInvariant() -eq '.zip') {
        Expand-Archive -LiteralPath $Bundle -DestinationPath $Stage -Force
        # Portable ZIP из package-portable.ps1 содержит общую корневую папку.
        # Распаковываем её содержимое в staging, сохраняя прежний формат архива.
        if (-not (Test-Path -LiteralPath (Join-Path $Stage 'release.json') -PathType Leaf)) {
            $topDirectories = @(Get-ChildItem -LiteralPath $Stage -Directory -Force)
            $topFiles = @(Get-ChildItem -LiteralPath $Stage -File -Force)
            if ($topDirectories.Count -eq 1 -and $topFiles.Count -eq 0 -and
                (Test-Path -LiteralPath (Join-Path $topDirectories[0].FullName 'release.json') -PathType Leaf)) {
                $archiveRoot = $topDirectories[0].FullName
                Get-ChildItem -LiteralPath $archiveRoot -Force | Move-Item -Destination $Stage
                Remove-Item -LiteralPath $archiveRoot -Force
            }
        }
    } else {
        throw 'Укажите каталог распакованного пакета или portable ZIP.'
    }
    Assert-WindowsReleaseTree $Stage
}

function Test-WindowsAppRunning([string] $InstallRoot) {
    $prefix = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') + '\'
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue)) {
        try {
            $imagePath = $process.Path
            if ($imagePath -and [IO.Path]::GetFullPath($imagePath).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                return $process
            }
        } catch {
            # Процесс другого пользователя или системный процесс может не отдавать путь.
        }
    }
    return $null
}

function Get-FreeLoopbackPort {
    $listener = New-Object Net.Sockets.TcpListener -ArgumentList @([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return [int]$listener.LocalEndpoint.Port
    } finally {
        $listener.Stop()
    }
}

function Stop-WindowsProcessTree([Diagnostics.Process] $Process) {
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            if (-not $Process.HasExited) { $Process.Kill() }
            $Process.WaitForExit(5000) | Out-Null
        }
    } catch {
        try { if (-not $Process.HasExited) { $Process.Kill() } } catch { }
    }
}

function Test-WindowsReleaseHealth([string] $ReleaseRoot, [int] $TimeoutSeconds) {
    Assert-WindowsReleaseTree $ReleaseRoot -AllowLegacy
    $port = Get-FreeLoopbackPort
    $probeRoot = Join-Path ([IO.Path]::GetTempPath()) ('ilt-probe-' + [guid]::NewGuid().ToString('N'))
    $dataRoot = Join-Path $probeRoot 'data'
    $componentRoot = Join-Path $probeRoot 'components'
    New-Item -ItemType Directory -Path $dataRoot, $componentRoot -Force | Out-Null
    $settings = @{ remote_bind = '127.0.0.1'; remote_port = $port; remote_enabled = $false } | ConvertTo-Json
    $settingsPath = Join-Path $dataRoot 'settings.json'
    [IO.File]::WriteAllText($settingsPath, $settings, (New-Object Text.UTF8Encoding($false)))
    $process = $null
    $ready = $false
    $healthVersion = ''
    $detail = 'Не удалось запустить проверку готовности.'
    $probeStep = 'подготовка'
    try {
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = Join-Path $ReleaseRoot 'sidecar\ImageLocalizationTool.exe'
        $start.Arguments = '--headless --remote'
        $start.WorkingDirectory = $ReleaseRoot
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
        $start.EnvironmentVariables['ILT_INSTALL_ROOT'] = $ReleaseRoot
        $start.EnvironmentVariables['ILT_DATA_DIR'] = $dataRoot
        $start.EnvironmentVariables['ILT_COMPONENT_ROOT'] = $componentRoot
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $start
        $probeStep = 'запуск sidecar'
        if (-not $process.Start()) { return [pscustomobject]@{ Ready = $false; Detail = 'Не удалось запустить sidecar.' } }
        $probeStep = 'ожидание health API'
        $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(1, $TimeoutSeconds))
        $uri = "http://127.0.0.1:$port/v1/health"
        while ([DateTime]::UtcNow -lt $deadline) {
            if ($process.HasExited) {
                $detail = "Sidecar завершился с кодом $($process.ExitCode)."
                break
            }
            try {
                $request = [Net.HttpWebRequest]::Create($uri)
                $request.Proxy = $null
                $request.Timeout = 700
                $request.ReadWriteTimeout = 700
                $response = $request.GetResponse()
                try {
                    $reader = New-Object IO.StreamReader($response.GetResponseStream())
                    $body = $reader.ReadToEnd()
                    $reader.Dispose()
                } finally { $response.Dispose() }
                $health = $body | ConvertFrom-Json
                if ($health.ready -eq $true) {
                    $ready = $true
                    $healthVersion = [string]$health.version
                    $detail = "Health API готов, приложение сообщает версию $($health.version)."
                    break
                }
            } catch {
                $detail = $_.Exception.Message
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready -and -not $process.HasExited -and [DateTime]::UtcNow -ge $deadline) {
            $detail = "Истёк тайм-аут $TimeoutSeconds сек."
        }
        Stop-WindowsProcessTree $process
        return [pscustomobject]@{ Ready = $ready; Detail = $detail; Version = $healthVersion }
    } catch {
        Stop-WindowsProcessTree $process
        return [pscustomobject]@{ Ready = $false; Detail = "$probeStep`: $($_.Exception.Message)"; Version = '' }
    } finally {
        Stop-WindowsProcessTree $process
        if (Test-Path -LiteralPath $probeRoot) { Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Remove-ReleasePlaceholders([string] $ReleaseRoot, [string] $FolderName) {
    $path = Join-Path $ReleaseRoot $FolderName
    if (-not (Test-Path -LiteralPath $path)) { return }
    $item = Get-Item -LiteralPath $path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "В пакете ссылка вместо пользовательского каталога: $FolderName" }
    if (-not $item.PSIsContainer) { throw "В пакете файл вместо пользовательского каталога: $FolderName" }
    $entries = @(Get-ChildItem -LiteralPath $path -Force -Recurse)
    foreach ($entry in $entries) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "В пакете пользовательских данных найдена ссылка: $($entry.FullName)" }
        if (-not $entry.PSIsContainer -and $entry.Name -ne '.keep') { throw "Portable-пакет не должен включать пользовательские данные: $($entry.FullName)" }
    }
    Remove-Item -LiteralPath $path -Recurse -Force
}

function Move-WindowsPersistentFolders([string] $SourceRoot, [string] $DestinationRoot) {
    $moved = New-Object 'System.Collections.Generic.List[string]'
    try {
        foreach ($name in $script:WindowsPersistentFolders) {
            $source = Join-Path $SourceRoot $name
            if (-not (Test-Path -LiteralPath $source)) { continue }
            $sourceItem = Get-Item -LiteralPath $source -Force
            if (($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Пользовательский каталог не может быть ссылкой: $name" }
            if (-not $sourceItem.PSIsContainer) { throw "Ожидался каталог пользовательских данных: $name" }
            $target = Join-Path $DestinationRoot $name
            Remove-ReleasePlaceholders $DestinationRoot $name
            Move-Item -LiteralPath $source -Destination $target
            $moved.Add($name)
        }
    } catch {
        foreach ($name in @($moved.ToArray()) | Sort-Object -Descending) {
            $source = Join-Path $DestinationRoot $name
            $target = Join-Path $SourceRoot $name
            if ((Test-Path -LiteralPath $source) -and -not (Test-Path -LiteralPath $target)) {
                Move-Item -LiteralPath $source -Destination $target -ErrorAction SilentlyContinue
            }
        }
        throw
    }
    return ,$moved.ToArray()
}

function Restore-WindowsPersistentFolders([string] $SourceRoot, [string] $DestinationRoot, [string[]] $Folders) {
    foreach ($name in $Folders) {
        $source = Join-Path $SourceRoot $name
        if (-not (Test-Path -LiteralPath $source)) { continue }
        $target = Join-Path $DestinationRoot $name
        if (Test-Path -LiteralPath $target) { throw "Нельзя восстановить пользовательские данные поверх существующего каталога: $target" }
        Move-Item -LiteralPath $source -Destination $target
    }
}

function Get-WindowsPreviousRelease([string] $InstallRoot) {
    $layout = Get-WindowsInstallLayout $InstallRoot
    if (-not (Test-Path -LiteralPath $layout.PreviousPointer -PathType Leaf)) { throw 'Сохранённая предыдущая версия не найдена.' }
    try { $pointer = Get-Content -LiteralPath $layout.PreviousPointer -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Не удалось прочитать указатель предыдущей версии: $($_.Exception.Message)" }
    if ($pointer.schema -ne 1 -or [string]$pointer.folder -notmatch '^[A-Za-z0-9._-]+$') { throw 'Некорректный указатель предыдущей версии.' }
    $path = Join-Path $layout.Parent ([string]$pointer.folder)
    if ([IO.Path]::GetFullPath((Split-Path -Parent $path)) -ne $layout.Parent) { throw 'Предыдущая версия находится вне каталога установки.' }
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw 'Каталог предыдущей версии отсутствует.' }
    Assert-WindowsReleaseTree $path
    $metadata = Get-WindowsReleaseMetadata $path
    if ([string]$metadata.version -ne [string]$pointer.version) { throw 'Версия не совпадает с указателем предыдущей версии.' }
    return [pscustomobject]@{ Path = $path; Metadata = $metadata; Layout = $layout }
}

function Set-WindowsPreviousRelease([string] $InstallRoot, [string] $PreviousPath, [string] $Version) {
    $layout = Get-WindowsInstallLayout $InstallRoot
    $folder = Split-Path -Leaf $PreviousPath
    if ([IO.Path]::GetFullPath((Split-Path -Parent $PreviousPath)) -ne $layout.Parent -or $folder -notmatch '^[A-Za-z0-9._-]+$') {
        throw 'Нельзя сохранить ссылку на каталог вне папки установки.'
    }
    $data = @{
        schema = 1
        folder = $folder
        version = $Version
        updated_at = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json
    $temporary = "$($layout.PreviousPointer).$PID.$([guid]::NewGuid().ToString('N')).tmp"
    $backup = "$($layout.PreviousPointer).$PID.$([guid]::NewGuid().ToString('N')).bak"
    try {
        Set-Content -LiteralPath $temporary -Encoding UTF8 -Value $data
        if (Test-Path -LiteralPath $layout.PreviousPointer) {
            [IO.File]::Replace($temporary, $layout.PreviousPointer, $backup)
        } else {
            [IO.File]::Move($temporary, $layout.PreviousPointer)
        }
    } finally {
        Remove-Item -LiteralPath $temporary, $backup -Force -ErrorAction SilentlyContinue
    }
}
