import 'dart:math' as math;
import 'dart:ui' show Offset, Rect, Size;

/// Аффинное преобразование сцены канваса: перенос + масштаб.
///
/// Зеркало геометрии веб-просмотрщика (`fitScale`/`currentScale`/зум к точке).
class ViewTransform {
  const ViewTransform({this.scale = 1, this.tx = 0, this.ty = 0});

  final double scale;
  final double tx;
  final double ty;

  static const double minScale = 0.10;
  static const double maxScale = 2.0;
  static const double stepPercent = 5;
  static const double _fitMargin = 16;

  static final List<double> _steps = [
    for (var percent = 10; percent <= 200; percent += 5) percent / 100,
  ];

  Offset toScreen(Offset scene) =>
      Offset(scene.dx * scale + tx, scene.dy * scale + ty);

  Offset toScene(Offset local) =>
      Offset((local.dx - tx) / scale, (local.dy - ty) / scale);

  Rect screenRect(Rect scene) => Rect.fromLTRB(
        scene.left * scale + tx,
        scene.top * scale + ty,
        scene.right * scale + tx,
        scene.bottom * scale + ty,
      );

  Rect sceneRect(Rect local) => Rect.fromLTRB(
        (local.left - tx) / scale,
        (local.top - ty) / scale,
        (local.right - tx) / scale,
        (local.bottom - ty) / scale,
      );

  ViewTransform translated(Offset delta) =>
      ViewTransform(scale: scale, tx: tx + delta.dx, ty: ty + delta.dy);

  /// Зум к точке: сцена под [focal] остаётся на месте.
  ViewTransform zoomAt(double nextScale, Offset focal) {
    final target = nextScale.clamp(minScale, maxScale);
    final k = target / scale;
    return ViewTransform(
      scale: target,
      tx: focal.dx - (focal.dx - tx) * k,
      ty: focal.dy - (focal.dy - ty) * k,
    );
  }

  /// Держим лист в пределах вьюпорта: меньше вьюпорта — по центру,
  /// больше — без пустых полей.
  ///
  /// [verticalMargin] добавляет пустой запас сверху и снизу, как доля высоты
  /// листа: у страницы выше вьюпорта можно «выехать» на ¼ листа, чтобы край
  /// не прилипал к краю окна. 0 — прежнее поведение.
  ViewTransform clamped(Size image, Size viewport, {double verticalMargin = 0}) {
    if (image.isEmpty || viewport.isEmpty) return this;
    final sw = image.width * scale;
    final sh = image.height * scale;
    final nx = sw <= viewport.width
        ? (viewport.width - sw) / 2
        : tx.clamp(viewport.width - sw, 0.0);
    final margin = sh * verticalMargin;
    final ny = sh <= viewport.height
        ? (viewport.height - sh) / 2
        : ty.clamp(viewport.height - sh - margin, margin);
    return ViewTransform(scale: scale, tx: nx, ty: ny);
  }

  /// Масштаб «вписать» (как `fitScale` в вебе: вьюпорт минус поля 16 px).
  static double fitScale(Size image, Size viewport) {
    if (image.isEmpty) return 1;
    final w = math.max(1, viewport.width - _fitMargin);
    final h = math.max(1, viewport.height - _fitMargin);
    return math.min(w / image.width, h / image.height);
  }

  /// Масштаб «по ширине».
  static double fitWidthScale(Size image, Size viewport) {
    if (image.isEmpty) return 1;
    return math.max(1, viewport.width - _fitMargin) / image.width;
  }

  static ViewTransform fit(Size image, Size viewport) {
    final scale = fitScale(image, viewport).clamp(minScale, maxScale);
    return ViewTransform(scale: scale).clamped(image, viewport);
  }

  static ViewTransform fitWidth(Size image, Size viewport) {
    final scale = fitWidthScale(image, viewport).clamp(minScale, maxScale);
    return ViewTransform(scale: scale).clamped(image, viewport);
  }

  static ViewTransform fixed(double scale, Size image, Size viewport) =>
      ViewTransform(scale: scale.clamp(minScale, maxScale))
          .clamped(image, viewport);

  /// Следующий/предыдущий шаг лестницы 10–200 % (как `zoomAt` в вебе).
  static double stepFrom(double scale, int direction) {
    if (direction > 0) {
      for (final step in _steps) {
        if (step > scale + 0.001) return step;
      }
      return maxScale;
    }
    for (final step in _steps.reversed) {
      if (step < scale - 0.001) return step;
    }
    return minScale;
  }

  @override
  bool operator ==(Object other) =>
      other is ViewTransform &&
      other.scale == scale &&
      other.tx == tx &&
      other.ty == ty;

  @override
  int get hashCode => Object.hash(scale, tx, ty);
}
