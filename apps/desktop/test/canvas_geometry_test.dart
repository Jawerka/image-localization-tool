import 'dart:ui' show Offset, Rect, Size;

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/model/view_transform.dart';
import 'package:ilt_desktop/src/ui/viewer/canvas_geometry.dart';

void main() {
  group('ViewTransform', () {
    test('fit вписывает лист с полем 16 px и центрирует', () {
      final transform = ViewTransform.fit(
        const Size(1000, 2000),
        const Size(800, 600),
      );
      final expected = (600 - 16) / 2000;
      expect(transform.scale, closeTo(expected, 1e-9));
      expect(transform.tx, closeTo((800 - 1000 * expected) / 2, 1e-9));
    });

    test('fitWidth считает по ширине', () {
      final transform = ViewTransform.fitWidth(
        const Size(1000, 2000),
        const Size(800, 600),
      );
      expect(transform.scale, closeTo(784 / 1000, 1e-9));
    });

    test('шаги 10–200 % по 5 %', () {
      expect(ViewTransform.stepFrom(0.99, 1), closeTo(1.0, 1e-9));
      expect(ViewTransform.stepFrom(1.0, 1), closeTo(1.05, 1e-9));
      expect(ViewTransform.stepFrom(1.0, -1), closeTo(0.95, 1e-9));
      expect(ViewTransform.stepFrom(0.10, -1), closeTo(0.10, 1e-9));
      expect(ViewTransform.stepFrom(2.0, 1), closeTo(2.0, 1e-9));
    });

    test('зум к точке держит сцену под курсором', () {
      const transform = ViewTransform(scale: 1, tx: 10, ty: 20);
      const focal = Offset(100, 80);
      final zoomed = transform.zoomAt(2, focal);
      expect(zoomed.scale, 2);
      expect(
        zoomed.toScene(focal).dx,
        closeTo(transform.toScene(focal).dx, 1e-9),
      );
      expect(
        zoomed.toScene(focal).dy,
        closeTo(transform.toScene(focal).dy, 1e-9),
      );
    });

    test('clamped не оставляет пустых полей при увеличении', () {
      const transform = ViewTransform(scale: 2, tx: -2000, ty: -3000);
      final clamped = transform.clamped(
        const Size(1000, 800),
        const Size(600, 400),
      );
      expect(clamped.tx, closeTo(600 - 2000, 1e-9));
      expect(clamped.ty, closeTo(400 - 1600, 1e-9));
    });

    test('clamped центрирует лист меньше вьюпорта', () {
      final clamped = const ViewTransform(
        scale: 0.5,
      ).clamped(const Size(200, 200), const Size(600, 400));
      expect(clamped.tx, closeTo(250, 1e-9));
      expect(clamped.ty, closeTo(150, 1e-9));
    });

    test('verticalMargin даёт пустой запас ¼ высоты листа', () {
      const image = Size(100, 400);
      const viewport = Size(300, 300);
      // sh = 400, запас 100: ty ∈ [-200, 100].
      final up = const ViewTransform(
        scale: 1,
        ty: -900,
      ).clamped(image, viewport, verticalMargin: 0.25);
      expect(up.ty, closeTo(-200, 1e-9));
      final down = const ViewTransform(
        scale: 1,
        ty: 900,
      ).clamped(image, viewport, verticalMargin: 0.25);
      expect(down.ty, closeTo(100, 1e-9));
      // Дефолт 0 — прежнее поведение без запаса.
      final tight = const ViewTransform(
        scale: 1,
        ty: 900,
      ).clamped(image, viewport);
      expect(tight.ty, 0);
      // Лист меньше вьюпорта по-прежнему центрируется.
      final small = const ViewTransform(
        scale: 0.5,
        ty: 900,
      ).clamped(const Size(200, 200), viewport, verticalMargin: 0.25);
      expect(small.ty, closeTo(100, 1e-9));
    });
  });

  group('хит-тест регионов', () {
    Region region(String id, Rect bbox) => Region({
      'id': id,
      'bbox': [bbox.left, bbox.top, bbox.width, bbox.height],
    });

    test('тело региона и запас 8 px', () {
      final regions = [region('1', const Rect.fromLTWH(100, 100, 200, 100))];
      const transform = ViewTransform();
      final inside = hitTestRegion(
        regions: regions,
        scenePoint: const Offset(150, 150),
        transform: transform,
      );
      expect(inside?.region.id, '1');
      expect(inside?.handle, '');
      // запас вне тела для невыделенного не срабатывает (как в вебе)
      final near = hitTestRegion(
        regions: regions,
        scenePoint: const Offset(305, 150),
        transform: transform,
      );
      expect(near, isNull);
    });

    test('ручки выделенного региона', () {
      final regions = [region('1', const Rect.fromLTWH(100, 100, 200, 100))];
      const transform = ViewTransform();
      final hit = hitTestRegion(
        regions: regions,
        scenePoint: const Offset(101, 199),
        transform: transform,
        selectedId: '1',
      );
      expect(hit?.handle, 'sw');
    });

    test('масштаб учитывается в запасе ручек', () {
      final regions = [region('1', const Rect.fromLTWH(100, 100, 200, 100))];
      final atHalf = hitTestRegion(
        regions: regions,
        scenePoint: const Offset(308, 150),
        transform: const ViewTransform(scale: 0.5),
        selectedId: '1',
      );
      expect(atHalf?.handle, 'e');
      final atFour = hitTestRegion(
        regions: regions,
        scenePoint: const Offset(308, 150),
        transform: const ViewTransform(scale: 4),
        selectedId: '1',
      );
      expect(atFour, isNull);
    });
  });

  group('геометрия жестов', () {
    test('applyHandleDrag: перенос и изменение размера', () {
      const start = Rect.fromLTWH(10, 10, 100, 50);
      expect(
        applyHandleDrag(handle: '', start: start, delta: const Offset(5, 6)),
        const Rect.fromLTWH(15, 16, 100, 50),
      );
      expect(
        applyHandleDrag(
          handle: 'se',
          start: start,
          delta: const Offset(10, 20),
        ),
        const Rect.fromLTWH(10, 10, 110, 70),
      );
      expect(
        applyHandleDrag(handle: 'nw', start: start, delta: const Offset(4, 5)),
        const Rect.fromLTWH(14, 15, 96, 45),
      );
    });

    test('pointerAngle и ручка поворота', () {
      const bbox = Rect.fromLTWH(0, 0, 100, 100);
      expect(pointerAngle(const Offset(100, 50), bbox), closeTo(0, 1e-9));
      expect(pointerAngle(const Offset(50, 100), bbox), closeTo(-90, 1e-9));
      final center = rotateHandleCenter(bbox, 1);
      expect(center, const Offset(50, -22));
      expect(hitRotateHandle(bbox, center, 1), isTrue);
    });

    test('warpPointsFor: quad и противоположная точка', () {
      final quad = Region({
        'id': '1',
        'bbox': [10, 20, 100, 50],
        'style': {
          'warp': {
            'kind': 'perspective',
            'quad': [
              [0, 0],
              [100, 0],
              [100, 50],
              [0, 50],
            ],
          },
        },
      });
      final points = warpPointsFor(quad);
      expect(points, hasLength(4));
      expect(points.first, const Offset(10, 20));
      expect(points.last, const Offset(10, 70));
      expect(warpOppositeIndex(0, mesh: false), 2);
      expect(warpOppositeIndex(0, mesh: true), 15);
      expect(warpOppositeIndex(5, mesh: true), 10);
    });

    test('неизвестный warp.kind не ломает регион', () {
      final region = Region({
        'id': '1',
        'bbox': [0, 0, 10, 10],
        'style': {
          'warp': {'kind': 'mystery'},
        },
      });
      expect(warpPointsFor(region), isEmpty);
    });

    test('mesh preview: 18 треугольников и текстурные координаты 4×4', () {
      expect(meshPreviewIndices(), hasLength(54));
      expect(meshPreviewIndices().take(6).toList(), [0, 1, 5, 0, 5, 4]);
      final coords = meshTextureCoordinates(301, 201);
      expect(coords, hasLength(16));
      expect(coords.first, Offset.zero);
      expect(coords[3], const Offset(300, 0));
      expect(coords[12], const Offset(0, 200));
      expect(coords.last, const Offset(300, 200));
    });

    test('buildMeshSurface сохраняет identity при подразбиении', () {
      const width = 120.0;
      const height = 80.0;
      const origin = Offset(100, 50);
      final control = [
        for (var row = 0; row < 4; row++)
          for (var col = 0; col < 4; col++)
            origin +
                Offset(col * (width - 1) / 3, row * (height - 1) / 3),
      ];
      final surface = buildMeshSurface(control, width, height, subdivisions: 4);
      expect(surface.positions, hasLength(9 * 25));
      expect(surface.indices, hasLength(9 * 4 * 4 * 6));
      for (var index = 0; index < surface.positions.length; index++) {
        final source = surface.textureCoordinates[index];
        expect(
          surface.positions[index].dx,
          closeTo(origin.dx + source.dx, 1e-6),
        );
        expect(
          surface.positions[index].dy,
          closeTo(origin.dy + source.dy, 1e-6),
        );
      }
    });

    test('buildWarpSurface: bend=0 и identity quad не меняют слой', () {
      const width = 120.0;
      const height = 80.0;
      const origin = Offset(100, 50);
      final identityQuad = [
        origin,
        origin + const Offset(width - 1, 0),
        origin + const Offset(width - 1, height - 1),
        origin + const Offset(0, height - 1),
      ];
      for (final kind in ['arc', 'wave', 'flag', 'ring', 'perspective']) {
        final surface = buildWarpSurface(
          kind: kind,
          width: width,
          height: height,
          origin: origin,
          bend: 0,
          quad: kind == 'perspective' ? identityQuad : null,
        );
        expect(surface.positions, hasLength(25 * 17), reason: kind);
        expect(surface.indices, hasLength(24 * 16 * 6), reason: kind);
        for (var index = 0; index < surface.positions.length; index++) {
          final source = surface.textureCoordinates[index];
          expect(
            surface.positions[index].dx,
            closeTo(origin.dx + source.dx, 1e-6),
            reason: kind,
          );
          expect(
            surface.positions[index].dy,
            closeTo(origin.dy + source.dy, 1e-6),
            reason: kind,
          );
        }
      }
    });

    test('buildWarpSurface: ненулевой bend двигает точки', () {
      const width = 120.0;
      const height = 80.0;
      const origin = Offset.zero;
      for (final kind in ['arc', 'wave', 'flag', 'ring']) {
        final surface = buildWarpSurface(
          kind: kind,
          width: width,
          height: height,
          origin: origin,
          bend: 1,
        );
        var moved = false;
        for (var index = 0; index < surface.positions.length; index++) {
          final source = surface.textureCoordinates[index];
          if ((surface.positions[index] - source).distance > 0.5) {
            moved = true;
            break;
          }
        }
        expect(moved, isTrue, reason: kind);
      }
    });
  });
}
