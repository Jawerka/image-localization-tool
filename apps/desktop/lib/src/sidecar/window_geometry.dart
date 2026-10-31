import 'dart:math' as math;
import 'dart:ui';

/// Геометрия главного окна в физических screen-координатах.
class WindowGeometry {
  const WindowGeometry({
    required this.monitor,
    required this.dpi,
    required this.work,
    required this.normal,
    required this.maximized,
  });

  final String monitor;
  final int dpi;
  final Rect work;
  final Rect normal;
  final bool maximized;

  Map<String, Object?> toJson() => {
    'version': 1,
    'monitor': monitor,
    'dpi': dpi,
    'work': _rectJson(work),
    'normal': _rectJson(normal),
    'maximized': maximized,
  };

  static WindowGeometry? fromJson(Object? value) {
    if (value is! Map || value['version'] != 1) return null;
    final monitor = value['monitor'];
    final dpi = value['dpi'];
    final work = _parseRect(value['work']);
    final normal = _parseRect(value['normal']);
    if (monitor is! String || monitor.isEmpty) return null;
    if (dpi is! int || dpi < 24 || dpi > 960) return null;
    if (work == null || normal == null) return null;
    if (work.width < 1 || work.height < 1) return null;
    if (normal.width < 1 || normal.height < 1) return null;
    return WindowGeometry(
      monitor: monitor,
      dpi: dpi,
      work: work,
      normal: normal,
      maximized: value['maximized'] == true,
    );
  }
}

/// Монитор в момент восстановления.
class ScreenInfo {
  const ScreenInfo({
    required this.name,
    required this.work,
    required this.dpi,
    required this.primary,
  });

  final String name;
  final Rect work;
  final int dpi;
  final bool primary;
}

/// Куда поставить окно и разворачивать ли его.
class ResolvedPlacement {
  const ResolvedPlacement({required this.rect, required this.maximized});

  final Rect rect;
  final bool maximized;
}

/// Восстановить нормальную геометрию на текущем наборе мониторов.
///
/// Размер хранится в логических px и пересчитывается под DPI целевого
/// монитора. Смещение от края рабочей области сохраняется, если рабочая
/// область не менялась; иначе переносится пропорционально. Итог всегда
/// целиком помещается в рабочую область.
ResolvedPlacement resolvePlacement(
  WindowGeometry saved,
  List<ScreenInfo> screens,
) {
  ScreenInfo? target;
  var sameMonitor = false;
  for (final screen in screens) {
    if (screen.name == saved.monitor) {
      target = screen;
      sameMonitor = true;
      break;
    }
  }
  if (target == null) {
    for (final screen in screens) {
      if (screen.primary) {
        target = screen;
        break;
      }
    }
  }
  if (target == null && screens.isNotEmpty) target = screens.first;
  if (target == null) {
    return ResolvedPlacement(rect: saved.normal, maximized: saved.maximized);
  }

  final savedScale = saved.dpi / 96;
  final targetScale = target.dpi / 96;
  final sameWorkspace = sameMonitor && saved.work == target.work;
  final workWidth = math.max(target.work.width, 1.0);
  final workHeight = math.max(target.work.height, 1.0);

  final width = math
      .min(saved.normal.width / savedScale * targetScale, workWidth)
      .roundToDouble();
  final height = math
      .min(saved.normal.height / savedScale * targetScale, workHeight)
      .roundToDouble();

  final double x;
  final double y;
  if (sameWorkspace) {
    x =
        target.work.left +
        (saved.normal.left - saved.work.left) / savedScale * targetScale;
    y =
        target.work.top +
        (saved.normal.top - saved.work.top) / savedScale * targetScale;
  } else {
    x =
        target.work.left +
        (saved.normal.left - saved.work.left) /
            math.max(saved.work.width, 1.0) *
            workWidth;
    y =
        target.work.top +
        (saved.normal.top - saved.work.top) /
            math.max(saved.work.height, 1.0) *
            workHeight;
  }

  final left = x
      .clamp(
        target.work.left,
        math.max(target.work.left, target.work.right - width),
      )
      .roundToDouble();
  final top = y
      .clamp(
        target.work.top,
        math.max(target.work.top, target.work.bottom - height),
      )
      .roundToDouble();

  return ResolvedPlacement(
    rect: Rect.fromLTWH(left, top, width, height),
    maximized: saved.maximized,
  );
}

List<int> _rectJson(Rect rect) => [
  rect.left.round(),
  rect.top.round(),
  rect.width.round(),
  rect.height.round(),
];

Rect? _parseRect(Object? value) {
  if (value is! List || value.length != 4) return null;
  if (value.any((item) => item is! num)) return null;
  final x = (value[0] as num).toDouble();
  final y = (value[1] as num).toDouble();
  final width = (value[2] as num).toDouble();
  final height = (value[3] as num).toDouble();
  if (!x.isFinite || !y.isFinite || !width.isFinite || !height.isFinite) {
    return null;
  }
  return Rect.fromLTWH(x, y, width, height);
}
