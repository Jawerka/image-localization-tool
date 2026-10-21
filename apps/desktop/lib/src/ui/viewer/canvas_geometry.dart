import 'dart:math' as math;
import 'dart:ui' show Offset, Rect;

import '../../model/page_document.dart';
import '../../model/view_transform.dart';

/// Попадание в регион: регион и ручка изменения размера (n/s/e/w).
class RegionHit {
  const RegionHit(this.region, this.handle);

  final Region region;

  /// Пустая строка — тело региона (перенос), иначе комбинация n/s/e/w.
  final String handle;
}

/// Хит-тест регионов как в вебе: сверху вниз, запас 8 экранных px.
RegionHit? hitTestRegion({
  required List<Region> regions,
  required Offset scenePoint,
  required ViewTransform transform,
  String? selectedId,
  double marginPx = 8,
}) {
  final margin = marginPx / transform.scale;
  for (final region in regions.reversed) {
    final rect = region.bbox;
    final near = Rect.fromLTRB(
      rect.left - margin,
      rect.top - margin,
      rect.right + margin,
      rect.bottom + margin,
    );
    if (!near.contains(scenePoint)) continue;
    var handle = '';
    if (region.id == selectedId) {
      if ((scenePoint.dy - rect.top).abs() <= margin) handle += 'n';
      if ((scenePoint.dy - rect.bottom).abs() <= margin) handle += 's';
      if ((scenePoint.dx - rect.left).abs() <= margin) handle += 'w';
      if ((scenePoint.dx - rect.right).abs() <= margin) handle += 'e';
      if (handle == 'ns' || handle == 'we' || handle.length > 2) handle = '';
    }
    final inside = rect.contains(scenePoint);
    if (inside || handle.isNotEmpty) return RegionHit(region, handle);
  }
  return null;
}

/// Центр ручки поворота: 22 экранных px над верхней гранью (12 px кружок + 10).
Offset rotateHandleCenter(Rect bbox, double scale) =>
    Offset(bbox.center.dx, bbox.top - 22 / scale);

/// Попадание в ручку поворота.
bool hitRotateHandle(Rect bbox, Offset scenePoint, double scale) =>
    (scenePoint - rotateHandleCenter(bbox, scale)).distance <= 10 / scale;

/// Центры ручек изменения размера (8 точек).
List<(String, Offset)> resizeHandlePoints(Rect bbox) => [
  ('nw', bbox.topLeft),
  ('n', Offset(bbox.center.dx, bbox.top)),
  ('ne', bbox.topRight),
  ('e', Offset(bbox.right, bbox.center.dy)),
  ('se', bbox.bottomRight),
  ('s', Offset(bbox.center.dx, bbox.bottom)),
  ('sw', bbox.bottomLeft),
  ('w', Offset(bbox.left, bbox.center.dy)),
];

/// Новый bbox при переносе/изменении размера (без клампа — клампит вызывающий).
Rect applyHandleDrag({
  required String handle,
  required Rect start,
  required Offset delta,
}) {
  var x = start.left;
  var y = start.top;
  var w = start.width;
  var h = start.height;
  if (handle.isEmpty) {
    x += delta.dx;
    y += delta.dy;
  } else {
    if (handle.contains('e')) w = start.width + delta.dx;
    if (handle.contains('s')) h = start.height + delta.dy;
    if (handle.contains('w')) {
      x = start.left + delta.dx;
      w = start.width - delta.dx;
    }
    if (handle.contains('n')) {
      y = start.top + delta.dy;
      h = start.height - delta.dy;
    }
  }
  return Rect.fromLTWH(x, y, math.max(1, w), math.max(1, h));
}

/// Угол указателя относительно центра bbox (градусы, как `pointerAngle`).
double pointerAngle(Offset point, Rect bbox) {
  final cx = bbox.center.dx;
  final cy = bbox.center.dy;
  return -math.atan2(point.dy - cy, point.dx - cx) * (180 / math.pi);
}

/// Точки искажения региона в координатах листа.
///
/// [kind] — `perspective` (quad) или `mesh`; null/неизвестный — пусто.
List<Offset> warpPointsFor(Region region) {
  final warp = region.warp;
  if (warp == null) return const [];
  final bbox = region.bbox;
  final kind = '${warp['kind'] ?? 'none'}';
  if (kind == 'perspective') {
    final raw = warp['quad'];
    final points =
        _pointList(raw, 4) ?? Region.defaultQuad(bbox.width, bbox.height);
    return [
      for (final point in points) bbox.topLeft + Offset(point[0], point[1]),
    ];
  }
  if (kind == 'mesh') {
    final raw = warp['mesh'];
    final points =
        _pointList(raw, 16) ?? Region.defaultMesh(bbox.width, bbox.height);
    return [
      for (final point in points) bbox.topLeft + Offset(point[0], point[1]),
    ];
  }
  return const [];
}

List<List<double>>? _pointList(Object? raw, int count) {
  if (raw is! List || raw.length != count) return null;
  final out = <List<double>>[];
  for (final item in raw) {
    if (item is! List || item.length < 2) return null;
    final x = item[0];
    final y = item[1];
    if (x is! num || y is! num) return null;
    out.add([x.toDouble(), y.toDouble()]);
  }
  return out;
}

/// Индекс противоположной точки для симметричного Shift-перетаскивания.
int warpOppositeIndex(int index, {required bool mesh}) {
  if (!mesh) return (index + 2) % 4;
  final row = index ~/ 4;
  final col = index % 4;
  return (3 - row) * 4 + (3 - col);
}

/// Индексы двух треугольников для каждой ячейки сетки 4×4.
List<int> meshPreviewIndices() {
  final indices = <int>[];
  for (var row = 0; row < 3; row++) {
    for (var col = 0; col < 3; col++) {
      final a = row * 4 + col;
      final b = a + 1;
      final c = a + 5;
      final d = a + 4;
      indices.addAll([a, b, c, a, c, d]);
    }
  }
  return indices;
}

/// Текстурные координаты вершин 4×4 для изображения [width]×[height].
List<Offset> meshTextureCoordinates(int width, int height) {
  final maxX = math.max(2, width - 1);
  final maxY = math.max(2, height - 1);
  return [
    for (var row = 0; row < 4; row++)
      for (var col = 0; col < 4; col++) Offset(col * maxX / 3, row * maxY / 3),
  ];
}

/// Готовые вершины для `Canvas.drawVertices` с подразбиением ячеек.
class MeshSurface {
  const MeshSurface({
    required this.positions,
    required this.textureCoordinates,
    required this.indices,
  });

  final List<Offset> positions;
  final List<Offset> textureCoordinates;
  final List<int> indices;
}

/// Билинейное подразбиение сетки 4×4: [control] — 16 узлов в координатах
/// страницы, текстура занимает весь слой [width]×[height].
MeshSurface buildMeshSurface(
  List<Offset> control,
  double width,
  double height, {
  int subdivisions = 4,
}) {
  if (control.length != 16 || width < 1 || height < 1) {
    return const MeshSurface(
      positions: [],
      textureCoordinates: [],
      indices: [],
    );
  }
  final steps = subdivisions < 1 ? 1 : subdivisions;
  final maxX = math.max(1.0, width - 1);
  final maxY = math.max(1.0, height - 1);
  final positions = <Offset>[];
  final textures = <Offset>[];
  final indices = <int>[];
  for (var cellRow = 0; cellRow < 3; cellRow++) {
    for (var cellCol = 0; cellCol < 3; cellCol++) {
      final p00 = control[cellRow * 4 + cellCol];
      final p10 = control[cellRow * 4 + cellCol + 1];
      final p01 = control[(cellRow + 1) * 4 + cellCol];
      final p11 = control[(cellRow + 1) * 4 + cellCol + 1];
      final base = positions.length;
      for (var iy = 0; iy <= steps; iy++) {
        final v = iy / steps;
        for (var ix = 0; ix <= steps; ix++) {
          final u = ix / steps;
          final x = p00.dx +
              u * (p10.dx - p00.dx) +
              v * (p01.dx - p00.dx) +
              u * v * (p11.dx - p10.dx - p01.dx + p00.dx);
          final y = p00.dy +
              u * (p10.dy - p00.dy) +
              v * (p01.dy - p00.dy) +
              u * v * (p11.dy - p10.dy - p01.dy + p00.dy);
          positions.add(Offset(x, y));
          textures.add(
            Offset((cellCol + u) / 3 * maxX, (cellRow + v) / 3 * maxY),
          );
        }
      }
      final stride = steps + 1;
      for (var iy = 0; iy < steps; iy++) {
        for (var ix = 0; ix < steps; ix++) {
          final a = base + iy * stride + ix;
          final b = a + 1;
          final c = a + stride + 1;
          final d = a + stride;
          indices.addAll([a, b, c, a, c, d]);
        }
      }
    }
  }
  return MeshSurface(
    positions: positions,
    textureCoordinates: textures,
    indices: indices,
  );
}


/// Сетка для локальных warp-ов без mesh: arc, wave, flag, ring, perspective.
MeshSurface buildWarpSurface({
  required String kind,
  required double width,
  required double height,
  required Offset origin,
  double bend = 0,
  List<Offset>? quad,
  int columns = 24,
  int rows = 16,
}) {
  if (width < 2 || height < 2) {
    return const MeshSurface(
      positions: [],
      textureCoordinates: [],
      indices: [],
    );
  }
  final nx = columns.clamp(1, 128);
  final ny = rows.clamp(1, 128);
  final maxX = width - 1;
  final maxY = height - 1;
  final centerX = maxX / 2;
  final centerY = maxY / 2;
  final radiusMax = math.max(centerX, centerY);
  final ampX = bend * width * 0.08;
  final ampY = bend * height * 0.08;
  final positions = <Offset>[];
  final textures = <Offset>[];
  final indices = <int>[];
  for (var iy = 0; iy <= ny; iy++) {
    final v = iy / ny;
    final sy = v * maxY;
    for (var ix = 0; ix <= nx; ix++) {
      final u = ix / nx;
      final sx = u * maxX;
      Offset dest;
      switch (kind) {
        case 'wave':
          var dx = sx;
          var dy = sy;
          for (var step = 0; step < 4; step++) {
            final nextX = sx + ampX * math.sin(2 * math.pi * dy / maxY);
            final nextY = sy + ampY * math.sin(2 * math.pi * dx / maxX);
            dx = nextX;
            dy = nextY;
          }
          dest = origin + Offset(dx, dy);
        case 'flag':
          dest = origin +
              Offset(sx, sy + ampY * math.sin(2 * math.pi * sx / maxX));
        case 'arc':
          final normX = (sx - centerX) / math.max(1.0, centerX);
          dest = origin +
              Offset(
                sx,
                sy - bend * height * (1 - normX * normX) + bend * width,
              );
        case 'ring':
          final sourceX = sx - centerX;
          final sourceY = sy - centerY;
          final sourceRadius = math.sqrt(sourceX * sourceX + sourceY * sourceY);
          final sourceAngle = math.atan2(sourceY, sourceX);
          var radius = sourceRadius;
          for (var step = 0; step < 6; step++) {
            final norm = radius / math.max(1.0, radiusMax);
            radius = sourceRadius * math.max(1.0 + bend * 0.2 * norm, 0.05);
          }
          final norm = radius / math.max(1.0, radiusMax);
          final angle = sourceAngle - bend * norm;
          dest = origin +
              Offset(
                centerX + radius * math.cos(angle),
                centerY + radius * math.sin(angle),
              );
        case 'perspective':
          dest = _perspectivePoint(sx, sy, maxX, maxY, quad) ??
              (origin + Offset(sx, sy));
        default:
          dest = origin + Offset(sx, sy);
      }
      positions.add(dest);
      textures.add(Offset(sx, sy));
    }
  }
  final stride = nx + 1;
  for (var iy = 0; iy < ny; iy++) {
    for (var ix = 0; ix < nx; ix++) {
      final a = iy * stride + ix;
      final b = a + 1;
      final c = a + stride + 1;
      final d = a + stride;
      indices.addAll([a, b, c, a, c, d]);
    }
  }
  return MeshSurface(
    positions: positions,
    textureCoordinates: textures,
    indices: indices,
  );
}

Offset? _perspectivePoint(
  double sx,
  double sy,
  double width,
  double height,
  List<Offset>? quad,
) {
  if (quad == null || quad.length != 4 || width < 1 || height < 1) return null;
  final x0 = quad[0].dx, y0 = quad[0].dy;
  final x1 = quad[1].dx, y1 = quad[1].dy;
  final x2 = quad[2].dx, y2 = quad[2].dy;
  final x3 = quad[3].dx, y3 = quad[3].dy;
  final dx1 = x1 - x2, dx2 = x3 - x2;
  final dy1 = y1 - y2, dy2 = y3 - y2;
  final dx3 = x0 - x1 + x2 - x3;
  final dy3 = y0 - y1 + y2 - y3;
  double a, b, c, d, e, f, g, h;
  final den = dx1 * dy2 - dx2 * dy1;
  if (dx3.abs() < 1e-9 && dy3.abs() < 1e-9) {
    a = x1 - x0;
    b = x2 - x1;
    c = x0;
    d = y1 - y0;
    e = y2 - y1;
    f = y0;
    g = 0;
    h = 0;
  } else if (den.abs() < 1e-9) {
    return null;
  } else {
    g = (dx3 * dy2 - dx2 * dy3) / den;
    h = (dx1 * dy3 - dx3 * dy1) / den;
    a = x1 - x0 + g * x1;
    b = x3 - x0 + h * x3;
    c = x0;
    d = y1 - y0 + g * y1;
    e = y3 - y0 + h * y3;
    f = y0;
  }
  final u = sx / width;
  final v = sy / height;
  final divisor = g * u + h * v + 1;
  if (divisor.abs() < 1e-9) return null;
  return Offset(
    (a * u + b * v + c) / divisor,
    (d * u + e * v + f) / divisor,
  );
}

/// Сцена под локальной точкой вьюпорта.
Offset scenePointAt(Offset local, ViewTransform transform) =>
    transform.toScene(local);
