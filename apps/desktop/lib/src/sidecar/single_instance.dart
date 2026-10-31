import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'data_root.dart';
import 'window_focus.dart';

/// Один экземпляр хоста: свой IPC-сокет и `instance.json` (владелец — хост).
///
/// Сайдкар `instance.json` не пишет. Второй запуск читает запись, шлёт
/// одну JSON-строку `{"paths": [...]}` и выходит; первый хост пересылает
/// пути в сайдкар через `POST /api/drop`.
class SingleInstance {
  SingleInstance({Map<String, String>? environment, String? executableDir})
      : this._(environment ?? Platform.environment, executableDir);

  SingleInstance._(this._environment, this._executableDir);

  final Map<String, String> _environment;
  final String? _executableDir;
  ServerSocket? _server;
  String? _recordPath;

  /// Отправить пути уже запущенному экземпляру. `true` — мы второй.
  Future<bool> forwardIfRunning(List<String> paths) async {
    final roots = dataRootCandidates(
      environment: _environment,
      executableDir: _executableDir,
      repoRoot: findRepoRoot(environment: _environment),
    );
    for (final root in roots) {
      final record = _readRecord(root);
      if (record == null) continue;
      try {
        final socket = await Socket.connect(
          InternetAddress.loopbackIPv4,
          record.port,
          timeout: const Duration(milliseconds: 500),
        );
        socket.write(jsonEncode({'paths': paths}));
        await socket.flush();
        socket.destroy();
        // Второй запуск в фокусе: передаём право первому вывести окно.
        allowForegroundTo(record.pid);
        return true;
      } catch (_) {
        continue;
      }
    }
    return false;
  }

  /// Поднять IPC-сервер и записать `instance.json`.
  Future<void> acquire({required void Function(List<String>) onPaths}) async {
    if (_server != null) return;
    final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    _server = server;
    final root = resolveDataRoot(
      environment: _environment,
      executableDir: _executableDir,
      repoRoot: findRepoRoot(environment: _environment),
    );
    Directory(root).createSync(recursive: true);
    _recordPath = '$root/instance.json';
    File(_recordPath!)
        .writeAsStringSync(jsonEncode({'pid': pid, 'port': server.port}));
    server.listen((socket) => _receive(socket, onPaths));
  }

  /// Убрать запись и закрыть IPC-сокет.
  Future<void> dispose() async {
    final server = _server;
    _server = null;
    await (server?.close());
    final record = _recordPath;
    _recordPath = null;
    if (record != null) {
      try {
        File(record).deleteSync();
      } on FileSystemException {
        // Уже удалён — ничего не делаем.
      }
    }
  }

  void _receive(Socket socket, void Function(List<String>) onPaths) {
    final buffer = BytesBuilder(copy: false);
    var handled = false;
    void handle() {
      if (handled) return;
      handled = true;
      try {
        final line = utf8.decode(buffer.takeBytes()).trim();
        if (line.isNotEmpty) {
          final decoded = jsonDecode(line);
          if (decoded is Map && decoded['paths'] is List) {
            final paths = <String>[
              for (final item in decoded['paths'] as List)
                if (item is String) item,
            ];
            onPaths(paths);
          }
        }
      } catch (_) {
        // Битая строка — игнорируем.
      }
      socket.destroy();
    }

    socket.listen(
      (data) {
        if (buffer.length < 1 << 20) buffer.add(data);
        if (data.contains(10)) handle();
      },
      onDone: handle,
      onError: (_) => handle(),
      cancelOnError: true,
    );
  }

  _InstanceRecord? _readRecord(String root) {
    try {
      final decoded = jsonDecode(File('$root/instance.json').readAsStringSync());
      if (decoded is! Map) return null;
      final port = decoded['port'];
      if (port is! int || port <= 0 || port > 65535) return null;
      final pid = decoded['pid'];
      return _InstanceRecord(port, pid is int && pid > 0 ? pid : 0);
    } catch (_) {
      return null;
    }
  }
}

class _InstanceRecord {
  const _InstanceRecord(this.port, this.pid);

  final int port;
  final int pid;
}
