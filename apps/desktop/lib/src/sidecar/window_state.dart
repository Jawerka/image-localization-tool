import 'dart:async';
import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:ui';

import 'package:ffi/ffi.dart' as ffi;
import 'package:win32/win32.dart';

import 'data_root.dart';
import 'window_focus.dart';
import 'window_geometry.dart';

/// Позиция и размер главного окна: `data/window.json`.
///
/// Геометрия хранится в физических screen-координатах. Нормальное положение
/// снимается через `GetWindowPlacement` (workspace-координаты переводятся
/// в screen), позиция обычного окна — через `GetWindowRect`.
class WindowState {
  WindowState();

  static const _pollInterval = Duration(milliseconds: 750);
  static const _maxWaitForShow = Duration(seconds: 10);

  late final String _recordPath =
      '${resolveDataRoot(repoRoot: findRepoRoot())}/window.json';

  Timer? _poll;
  String? _lastSaved;
  bool _maximizeOnStart = false;

  /// Поставить окно на сохранённое место. Вызывать до `runApp`.
  void restore() {
    if (!Platform.isWindows) return;
    final saved = _read();
    final hwnd = findMainWindow();
    if (saved == null || hwnd == null) return;
    final screens = _screens();
    if (screens.isEmpty) return;
    final placement = resolvePlacement(saved, screens);
    final rect = placement.rect;
    SetWindowPos(
      hwnd,
      null,
      rect.left.round(),
      rect.top.round(),
      rect.width.round(),
      rect.height.round(),
      SET_WINDOW_POS_FLAGS(SWP_NOZORDER | SWP_NOACTIVATE),
    );
    _maximizeOnStart = placement.maximized;
  }

  /// Запустить polling и применить maximize после первого кадра.
  void start() {
    if (!Platform.isWindows) return;
    if (_maximizeOnStart) {
      _maximizeOnStart = false;
      unawaited(_maximizeWhenVisible().whenComplete(_startPolling));
    } else {
      _startPolling();
    }
  }

  /// Сохранить геометрию и остановить polling (перед выходом).
  void saveNow() {
    _poll?.cancel();
    _poll = null;
    save();
  }

  void save() {
    if (!Platform.isWindows) return;
    final hwnd = findMainWindow();
    if (hwnd == null || IsIconic(hwnd)) return;
    final geometry = _snapshot(hwnd);
    if (geometry == null) return;
    final json = jsonEncode(geometry.toJson());
    if (json == _lastSaved) return;
    try {
      File(_recordPath).writeAsStringSync(json);
      _lastSaved = json;
    } on FileSystemException {
      // Диск недоступен — повторим на следующем тике.
    }
  }

  void _startPolling() {
    _poll ??= Timer.periodic(_pollInterval, (_) => save());
  }

  Future<void> _maximizeWhenVisible() async {
    final hwnd = findMainWindow();
    if (hwnd == null) return;
    final deadline = DateTime.now().add(_maxWaitForShow);
    while (!IsWindowVisible(hwnd) && DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 16));
    }
    if (IsWindowVisible(hwnd)) ShowWindow(hwnd, SW_MAXIMIZE);
  }

  WindowGeometry? _snapshot(HWND hwnd) {
    final screens = _screens();
    if (screens.isEmpty) return null;
    final monitor = _monitorInfo(
      MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST),
    );
    if (monitor == null) return null;
    ScreenInfo primary = screens.first;
    for (final screen in screens) {
      if (screen.primary) {
        primary = screen;
        break;
      }
    }
    final maximized = IsZoomed(hwnd);
    final normal = _normalRect(hwnd, maximized, primary.work);
    if (normal == null) return null;
    final dpi = GetDpiForWindow(hwnd);
    return WindowGeometry(
      monitor: monitor.name,
      dpi: dpi > 0 ? dpi : monitor.dpi,
      work: monitor.work,
      normal: normal,
      maximized: maximized,
    );
  }

  Rect? _normalRect(HWND hwnd, bool maximized, Rect primaryWork) {
    if (!maximized) return _windowRect(hwnd);
    return ffi.using((arena) {
      final placement = arena<WINDOWPLACEMENT>();
      placement.ref.length = sizeOf<WINDOWPLACEMENT>();
      if (!GetWindowPlacement(hwnd, placement).value) return null;
      final rect = placement.ref.rcNormalPosition;
      return Rect.fromLTWH(
        (rect.left + primaryWork.left).toDouble(),
        (rect.top + primaryWork.top).toDouble(),
        (rect.right - rect.left).toDouble(),
        (rect.bottom - rect.top).toDouble(),
      );
    });
  }

  Rect? _windowRect(HWND hwnd) {
    return ffi.using((arena) {
      final rect = arena<RECT>();
      if (!GetWindowRect(hwnd, rect).value) return null;
      return Rect.fromLTWH(
        rect.ref.left.toDouble(),
        rect.ref.top.toDouble(),
        (rect.ref.right - rect.ref.left).toDouble(),
        (rect.ref.bottom - rect.ref.top).toDouble(),
      );
    });
  }

  WindowGeometry? _read() {
    try {
      final decoded = jsonDecode(File(_recordPath).readAsStringSync());
      return WindowGeometry.fromJson(decoded);
    } on FileSystemException {
      return null;
    } on FormatException {
      return null;
    }
  }

  List<ScreenInfo> _screens() {
    final screens = <ScreenInfo>[];
    final callback = NativeCallable<MONITORENUMPROC>.isolateLocal((
      Pointer monitor,
      Pointer hdc,
      Pointer<RECT> rect,
      int data,
    ) {
      final info = _monitorInfo(HMONITOR(monitor));
      if (info != null) screens.add(info);
      return 1;
    }, exceptionalReturn: 0);
    try {
      EnumDisplayMonitors(null, null, callback.nativeFunction, LPARAM(0));
    } finally {
      callback.close();
    }
    return screens;
  }

  ScreenInfo? _monitorInfo(HMONITOR monitor) {
    return ffi.using((arena) {
      final info = arena<MONITORINFOEX>();
      info.ref.monitorInfo.cbSize = sizeOf<MONITORINFOEX>();
      if (!GetMonitorInfo(monitor, info.cast<MONITORINFO>())) return null;
      final data = info.ref.monitorInfo;
      return ScreenInfo(
        name: info.ref.szDevice,
        work: Rect.fromLTRB(
          data.rcWork.left.toDouble(),
          data.rcWork.top.toDouble(),
          data.rcWork.right.toDouble(),
          data.rcWork.bottom.toDouble(),
        ),
        dpi: _dpiFor(monitor),
        primary: (data.dwFlags & MONITORINFOF_PRIMARY) != 0,
      );
    });
  }

  int _dpiFor(HMONITOR monitor) {
    return ffi.using((arena) {
      final x = arena<Uint32>();
      final y = arena<Uint32>();
      try {
        GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, x, y);
        return x.value > 0 ? x.value : 96;
      } on WindowsException {
        return 96;
      }
    });
  }
}
