import 'dart:io';

/// Открыть папку в системном файловом менеджере.
Future<void> openFolder(String path) async {
  if (path.isEmpty) return;
  try {
    if (Platform.isWindows) {
      await Process.start('explorer.exe', [path]);
    } else if (Platform.isMacOS) {
      await Process.start('open', [path]);
    } else {
      await Process.start('xdg-open', [path]);
    }
  } catch (_) {
    // Путь недоступен — молча игнорируем, это некритичное действие.
  }
}

/// Открыть файл приложением по умолчанию (лог, данные).
Future<void> openPath(String path) async {
  if (path.isEmpty) return;
  try {
    if (Platform.isWindows) {
      await Process.start('cmd', ['/c', 'start', '', path]);
    } else if (Platform.isMacOS) {
      await Process.start('open', [path]);
    } else {
      await Process.start('xdg-open', [path]);
    }
  } catch (_) {
    // Некритичное действие.
  }
}
