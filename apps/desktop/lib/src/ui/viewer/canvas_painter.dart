import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'canvas_geometry.dart';

/// Кисти и метки сцены.
final _imagePaint = Paint()..filterQuality = FilterQuality.medium;
final _chipShadow = Paint()
  ..style = PaintingStyle.stroke
  ..strokeWidth = 1
  ..color = const Color(0x66000000);

/// Рисует лист, шторку сравнения, маску, рамки регионов и превью жестов
/// одним пассом в координатах листа.
///
/// Transform рисует `InteractiveViewer` — единственный его владелец
/// (см. вариант `uncached` в spike.md); painter его НЕ применяет. Размеры
/// вырожденческих элементов (рамки, номера, ручки) компенсируются `1/scale`,
/// чтобы на экране они оставались постоянными — как CSS-элементы
/// веб-просмотрщика. Сцена намеренно без `RepaintBoundary` (см. spike.md).
class ScenePainter extends CustomPainter {
  ScenePainter({
    required this.viewer,
    required this.session,
    required this.palette,
  });

  final ViewerState viewer;
  final CanvasSession session;
  final IltPalette palette;

  static final Map<String, TextPainter> _labelCache = {};

  @override
  void paint(Canvas canvas, Size size) {
    final scale = session.transform.scale <= 0 ? 1.0 : session.transform.scale;
    _paintScene(canvas, scale);
  }

  void _paintScene(Canvas canvas, double scale) {
    final view = viewer.view;
    final base = viewer.imageFor(view == 'original' ? 'original' : 'result');
    final imageSize = viewer.imageSize;
    if (base != null) {
      _drawImage(canvas, base);
    } else if (view != 'original' || imageSize.isEmpty) {
      _drawPlaceholder(canvas, imageSize, scale);
    }

    if (view == 'compare') {
      final original = viewer.imageFor('original');
      if (original != null) {
        final width = original.width.toDouble();
        final height = original.height.toDouble();
        final edge = width * viewer.curtain;
        canvas.save();
        canvas.clipRect(ui.Rect.fromLTWH(0, 0, edge, height));
        _drawImage(canvas, original);
        canvas.restore();
        _drawCurtainChrome(canvas, width, height, edge, scale);
      }
    }

    if (viewer.showMask) {
      final mask = viewer.imageFor('mask');
      if (mask != null) {
        final rect = ui.Rect.fromLTWH(
          0,
          0,
          mask.width.toDouble(),
          mask.height.toDouble(),
        );
        canvas.saveLayer(
          rect,
          Paint()
            ..blendMode = BlendMode.multiply
            ..color = const Color(0x80FFFFFF),
        );
        canvas.drawImageRect(mask, rect, rect, Paint());
        canvas.restore();
      }
    }

    final preview = viewer.stylePreviewImage;
    if (preview != null) {
      final src = ui.Rect.fromLTWH(
        0,
        0,
        preview.width.toDouble(),
        preview.height.toDouble(),
      );
      final textOffset = session.previewTextId == viewer.selectedRegionId
          ? session.previewTextOffset ?? Offset.zero
          : Offset.zero;
      final region = viewer.document?.findRegion(viewer.selectedRegionId);
      final meshPoints = session.previewWarpPoints;
      if (meshPoints != null &&
          meshPoints.length == 16 &&
          region?.warp?['kind'] == 'mesh') {
        _drawMeshPreview(canvas, preview, meshPoints);
      } else {
        canvas.drawImageRect(
          preview,
          src,
          src.shift(viewer.stylePreviewOffset + textOffset),
          _imagePaint,
        );
      }
    }

    final document = viewer.document;
    if (document != null && viewer.showBoxes) {
      _paintRegions(canvas, document, scale);
    }
    _paintPreviews(canvas, scale);
  }

  void _drawImage(Canvas canvas, ui.Image image) {
    final rect = ui.Rect.fromLTWH(
      0,
      0,
      image.width.toDouble(),
      image.height.toDouble(),
    );
    canvas.drawImageRect(image, rect, rect, _imagePaint);
  }

  // shortcut: черновой mesh-превью искажает точный crop вместе с фоном.
  // Заменить на RGBA base-layer, когда 039 получит полноценную приёмку.
  void _drawMeshPreview(Canvas canvas, ui.Image image, List<Offset> points) {
    final vertices = ui.Vertices(
      ui.VertexMode.triangles,
      points,
      textureCoordinates: meshTextureCoordinates(image.width, image.height),
      indices: meshPreviewIndices(),
    );
    final shader = ui.ImageShader(
      image,
      ui.TileMode.clamp,
      ui.TileMode.clamp,
      Matrix4.identity().storage,
      filterQuality: FilterQuality.medium,
    );
    canvas.drawVertices(
      vertices,
      BlendMode.srcOver,
      Paint()
        ..shader = shader
        ..filterQuality = FilterQuality.medium,
    );
  }

  void _drawPlaceholder(Canvas canvas, ui.Size imageSize, double scale) {
    final width = imageSize.isEmpty ? 720.0 : imageSize.width;
    final height = imageSize.isEmpty ? 960.0 : imageSize.height;
    final rect = ui.Rect.fromLTWH(0, 0, width, height);
    canvas.drawRect(rect, Paint()..color = const Color(0xFF151A24));
    canvas.drawRect(
      rect.deflate(2 / scale),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2 / scale
        ..color = const Color(0xFF2A3345),
    );
    final label = _label(
      'Результат появится после прогона',
      size: 15,
      color: palette.textMuted,
    );
    canvas.save();
    canvas.translate(rect.center.dx, rect.center.dy);
    canvas.scale(1 / scale);
    label.paint(canvas, ui.Offset(-label.width / 2, -label.height / 2));
    canvas.restore();
  }

  void _drawCurtainChrome(
    Canvas canvas,
    double width,
    double height,
    double edge,
    double scale,
  ) {
    final bar = Paint()..color = const Color(0xF2FFFFFF);
    canvas.drawRect(
      ui.Rect.fromLTWH(edge - 1 / scale, 0, 2 / scale, height),
      bar,
    );
    canvas.drawRect(
      ui.Rect.fromLTWH(edge - 2 / scale, 0, 4 / scale, height),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1 / scale
        ..color = const Color(0x88000000),
    );
    _chip(
      canvas,
      ui.Offset(6 / scale, 6 / scale),
      'Оригинал',
      const Color(0xF2FFFFFF),
      const Color(0xFF11151C),
      scale,
    );
    _chip(
      canvas,
      ui.Offset(width - 6 / scale, 6 / scale),
      'Результат',
      const Color(0xF2FFFFFF),
      const Color(0xFF11151C),
      scale,
      rightAlign: true,
    );
    final grip = ui.Rect.fromLTWH(
      edge - 6 / scale,
      height / 2 - 14 / scale,
      12 / scale,
      28 / scale,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(grip, Radius.circular(3 / scale)),
      Paint()..color = const Color(0xFF1B2230),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(grip, Radius.circular(3 / scale)),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1 / scale
        ..color = const Color(0xAAFFFFFF),
    );
  }

  void _paintRegions(Canvas canvas, PageDocument document, double scale) {
    final selectedId = viewer.selectedRegionId;
    for (var index = 0; index < document.regions.length; index++) {
      final region = document.regions[index];
      final isSelected = region.id == selectedId;
      var rect = region.bbox;
      if (session.previewRegionId == region.id && session.previewRect != null) {
        rect = session.previewRect!;
      }
      _paintRegionBox(
        canvas,
        rect,
        number: index + 1,
        selected: isSelected,
        skip: region.skip,
        overflow: region.overflow,
        sfx: region.isSfx,
        scale: scale,
      );
      if (isSelected) {
        _paintSelection(canvas, rect, scale);
        _paintWarpPoints(canvas, region, scale);
      }
    }
  }

  void _paintRegionBox(
    Canvas canvas,
    ui.Rect rect, {
    required int number,
    required bool selected,
    required bool skip,
    required bool overflow,
    required bool sfx,
    required double scale,
  }) {
    final ringColor = selected
        ? palette.primary
        : overflow
        ? palette.textWarning
        : sfx
        ? const Color(0xFFE05252)
        : null;
    canvas.drawRect(
      rect,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5 / scale
        ..color = const Color(0xE6FFFFFF),
    );
    canvas.drawRect(
      rect.inflate(1.5 / scale),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1 / scale
        ..color = const Color(0x88000000),
    );
    if (ringColor != null && !selected) {
      canvas.drawRect(
        rect.inflate(3 / scale),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5 / scale
          ..color = ringColor,
      );
    }
    if (skip) {
      _dashedRect(canvas, rect, scale, const Color(0xE6FFFFFF));
    }
    _chip(
      canvas,
      rect.topLeft,
      '$number',
      const Color(0xF2FFFFFF),
      const Color(0xFF11151C),
      scale,
    );
    final flag = skip
        ? 'пропущен'
        : overflow
        ? 'не влез'
        : sfx
        ? 'звук'
        : '';
    if (flag.isNotEmpty) {
      _chip(
        canvas,
        rect.topRight,
        flag,
        const Color(0xF2FFFFFF),
        overflow
            ? palette.textWarning
            : sfx
            ? const Color(0xFFE05252)
            : const Color(0xFF11151C),
        scale,
        rightAlign: true,
      );
    }
  }

  void _paintSelection(Canvas canvas, ui.Rect rect, double scale) {
    canvas.drawRect(
      rect.inflate(3 / scale),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5 / scale
        ..color = palette.primary,
    );
    final handlePaint = Paint()..color = const Color(0xF2FFFFFF);
    final handleBorder = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5 / scale
      ..color = palette.primary;
    for (final (_, point) in resizeHandlePoints(rect)) {
      final handle = ui.Rect.fromCenter(
        center: point,
        width: 8 / scale,
        height: 8 / scale,
      );
      canvas.drawRect(handle, handlePaint);
      canvas.drawRect(handle, handleBorder);
    }
    final rotate = rotateHandleCenter(rect, scale);
    canvas.drawLine(
      ui.Offset(rect.center.dx, rect.top),
      rotate,
      Paint()
        ..strokeWidth = 1.5 / scale
        ..color = palette.primary,
    );
    canvas.drawCircle(rotate, 6 / scale, handlePaint);
    canvas.drawCircle(
      rotate,
      6 / scale,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2 / scale
        ..color = palette.primary,
    );
  }

  void _paintWarpPoints(Canvas canvas, Region region, double scale) {
    final points =
        session.previewWarpId == region.id && session.previewWarpPoints != null
        ? session.previewWarpPoints!
        : warpPointsFor(region);
    if (points.isEmpty) return;
    final border = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2 / scale
      ..color = const Color(0xFFE05252);
    final fill = Paint()..color = const Color(0xF2FFFFFF);
    for (final point in points) {
      canvas.drawCircle(point, 5 / scale, fill);
      canvas.drawCircle(point, 5 / scale, border);
    }
  }

  void _paintPreviews(Canvas canvas, double scale) {
    final draft = session.draftRect;
    if (draft != null) {
      _dashedRect(canvas, draft, scale, palette.primary);
    }
    final stroke = session.strokePoints;
    if (stroke.isNotEmpty) {
      final color = session.strokeMode == Stroke.erase
          ? const Color(0x8C2563EB)
          : const Color(0x8C16A34A);
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = math.max(1, viewer.brushSize) * 2
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = color;
      final dot = Paint()..color = color;
      if (stroke.length == 1) {
        canvas.drawCircle(stroke.first, math.max(1, viewer.brushSize), dot);
      } else {
        final path = ui.Path()..moveTo(stroke.first.dx, stroke.first.dy);
        for (final point in stroke.skip(1)) {
          path.lineTo(point.dx, point.dy);
        }
        canvas.drawPath(path, paint);
      }
    }
    final lasso = session.lasso;
    if (lasso.isNotEmpty) {
      final color = session.lassoMode == 'erase_fill'
          ? const Color(0x8C2563EB)
          : const Color(0x8C16A34A);
      final points = [
        ...lasso,
        if (session.lassoHover != null) session.lassoHover!,
      ];
      if (points.length >= 3) {
        final path = ui.Path()..moveTo(points.first.dx, points.first.dy);
        for (final point in points.skip(1)) {
          path.lineTo(point.dx, point.dy);
        }
        path.close();
        canvas.drawPath(path, Paint()..color = color.withValues(alpha: 0.28));
      }
      if (points.length >= 2) {
        final outline = ui.Path()..moveTo(points.first.dx, points.first.dy);
        for (final point in points.skip(1)) {
          outline.lineTo(point.dx, point.dy);
        }
        canvas.drawPath(
          outline,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2 / scale
            ..color = color,
        );
      }
      final dot = Paint()..color = color;
      for (final point in lasso) {
        canvas.drawCircle(point, 3 / scale, dot);
      }
    }
  }

  void _dashedRect(Canvas canvas, ui.Rect rect, double scale, Color color) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5 / scale
      ..color = color;
    final dash = 6 / scale;
    final gap = 4 / scale;
    void line(ui.Offset from, ui.Offset to) {
      final total = (to - from).distance;
      if (total <= 0) return;
      final direction = (to - from) / total;
      var travelled = 0.0;
      while (travelled < total) {
        final end = math.min(travelled + dash, total);
        canvas.drawLine(
          from + direction * travelled,
          from + direction * end,
          paint,
        );
        travelled = end + gap;
      }
    }

    line(rect.topLeft, rect.topRight);
    line(rect.topRight, rect.bottomRight);
    line(rect.bottomRight, rect.bottomLeft);
    line(rect.bottomLeft, rect.topLeft);
  }

  void _chip(
    Canvas canvas,
    ui.Offset anchor,
    String text,
    Color background,
    Color foreground,
    double scale, {
    bool rightAlign = false,
  }) {
    final label = _label(text, size: 11, color: foreground);
    final width = label.width + 6;
    final height = label.height + 2;
    final left = rightAlign ? anchor.dx - width : anchor.dx;
    canvas.save();
    canvas.translate(left, anchor.dy);
    canvas.scale(1 / scale);
    final rect = ui.Rect.fromLTWH(0, 0, width, height);
    canvas.drawRect(rect, Paint()..color = background);
    canvas.drawRect(rect, _chipShadow);
    label.paint(canvas, const ui.Offset(3, 1));
    canvas.restore();
  }

  TextPainter _label(
    String text, {
    required double size,
    required Color color,
  }) {
    final key = '$text|$size|${color.toARGB32()}';
    final cached = _labelCache[key];
    if (cached != null) return cached;
    final painter = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          fontSize: size,
          height: 1.15,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    if (_labelCache.length > 200) _labelCache.clear();
    _labelCache[key] = painter;
    return painter;
  }

  @override
  bool shouldRepaint(covariant ScenePainter oldDelegate) => true;
}
