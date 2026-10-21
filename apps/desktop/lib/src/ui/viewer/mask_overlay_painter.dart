import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../model/page_document.dart';

/// Полупрозрачный слой маски: чёрный негатив серверной маски и цветные
/// следы ручных назначений. Цвет заменяет затемнение, а не накладывается
/// поверх него, поэтому пересечения не темнеют.
class MaskOverlayPainter {
  const MaskOverlayPainter({
    required this.mask,
    required this.bounds,
    required this.strokes,
    this.bakedStrokeCount = 0,
    this.activeStroke,
    this.fillPreviews = const {},
  });

  /// Светло-зелёный: добавлено кистью или заливкой.
  static const addColor = Color(0xFF90EE90);

  /// Светло-красный: исключено ластиком или заливкой.
  static const removeColor = Color(0xFFFF9999);

  static const _blackFromMask = ColorFilter.matrix(<double>[
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    -1,
    0,
    0,
    0,
    255,
  ]);

  final ui.Image? mask;
  final ui.Rect bounds;
  final List<Stroke> strokes;

  /// Сколько первых штрихов уже входит в [mask]; их не рисуем и не красим.
  final int bakedStrokeCount;
  final Stroke? activeStroke;
  final Map<String, FillPreview> fillPreviews;

  static Color colorFor(String mode) =>
      mode == Stroke.erase ||
          mode == Stroke.eraseFill ||
          mode == Stroke.eraseFlood
      ? removeColor
      : addColor;

  void paint(Canvas canvas) {
    if (bounds.isEmpty) return;
    canvas.save();
    canvas.clipRect(bounds);
    canvas.saveLayer(bounds, Paint()..color = const Color(0x80FFFFFF));
    final image = mask;
    if (image != null) {
      final source = ui.Rect.fromLTWH(
        0,
        0,
        image.width.toDouble(),
        image.height.toDouble(),
      );
      canvas.drawImageRect(
        image,
        source,
        bounds,
        Paint()..colorFilter = _blackFromMask,
      );
    }
    final baked = bakedStrokeCount < 0
        ? 0
        : math.min(bakedStrokeCount, strokes.length);
    for (final stroke in strokes.skip(baked)) {
      _paintStroke(canvas, stroke);
    }
    final active = activeStroke;
    if (active != null) _paintStroke(canvas, active);
    canvas.restore();
    canvas.restore();
  }

  void _paintStroke(Canvas canvas, Stroke stroke) {
    final points = stroke.points;
    if (points.isEmpty) return;
    if (stroke.mode == Stroke.flood || stroke.mode == Stroke.eraseFlood) {
      final preview = fillPreviews[fillStrokeKey(stroke)];
      if (preview != null) {
        canvas.drawImage(preview.image, preview.offset, Paint());
      }
      return;
    }
    final paint = Paint()..color = colorFor(stroke.mode);
    if (stroke.mode == Stroke.fill || stroke.mode == Stroke.eraseFill) {
      if (points.length < 3) return;
      final path = ui.Path()..moveTo(points.first.dx, points.first.dy);
      for (final point in points.skip(1)) {
        path.lineTo(point.dx, point.dy);
      }
      path.close();
      canvas.drawPath(path, paint);
      return;
    }
    final radius = math.max(1.0, stroke.radius);
    if (points.length == 1) {
      canvas.drawCircle(points.first, radius, paint);
      return;
    }
    final path = ui.Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    canvas.drawPath(
      path,
      paint
        ..style = PaintingStyle.stroke
        ..strokeWidth = radius * 2
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }
}
