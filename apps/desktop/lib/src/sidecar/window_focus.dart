import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart' as ffi;
import 'package:win32/win32.dart';

/// Заголовок главного окна (`windows/runner/main.cpp`).
const _windowTitle = 'Image Localization Tool';

/// Разрешить процессу [pid] вывести своё окно на передний план.
///
/// Вызывает процесс второго запуска: он в фокусе и вправе передать право
/// первому экземпляру, иначе `SetForegroundWindow` у того не сработает.
void allowForegroundTo(int pid) {
  if (!Platform.isWindows || pid <= 0) return;
  AllowSetForegroundWindow(pid);
}

/// Восстановить и сфокусировать главное окно (свёрнутое — развернуть).
///
/// `pid` ограничивает поиск своим процессом. `false`, если окно не найдено
/// или фокус не передан.
bool focusMainWindow({int? pid}) {
  if (!Platform.isWindows) return false;
  var focused = false;
  ffi.using((arena) {
    final title = _windowTitle.toPcwstr(allocator: arena);
    final hwnd = FindWindow(null, title).value;
    if (hwnd.address == 0) return;
    if (pid != null && pid > 0) {
      final owner = arena.allocate<Uint32>(sizeOf<Uint32>());
      GetWindowThreadProcessId(hwnd, owner);
      if (owner.value != pid) return;
    }
    if (IsIconic(hwnd)) {
      ShowWindow(hwnd, SW_RESTORE);
    }
    focused = SetForegroundWindow(hwnd);
  });
  return focused;
}
