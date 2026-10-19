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

/// Сцена под локальной точкой вьюпорта.
Offset scenePointAt(Offset local, ViewTransform transform) =>
    transform.toScene(local);
