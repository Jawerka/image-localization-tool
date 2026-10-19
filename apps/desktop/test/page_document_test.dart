import 'dart:ui' show Offset, Rect;

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/model/page_document.dart';

void main() {
  test('нормализация сохраняет неизвестные поля и приводит известные', () {
    final document = PageDocument.fromJson(<String, dynamic>{
      'version': '4',
      'regions': [
        {
          'id': 1,
          'bbox': [1, 2, 3, 4],
          'custom': 'keep',
          'style': {
            'warp': {'kind': 'arc', 'bend': 12},
          },
        },
      ],
      'strokes': [
        {
          'mode': 'erase',
          'radius': 0,
          'points': [
            [1, 2],
            [3],
          ],
        },
      ],
      'warnings': ['a', 2],
      'extra_top': true,
    });
    expect(document.version, 4);
    expect(document.regions, hasLength(1));
    final region = document.regions.first;
    expect(region.id, '1');
    expect(region.bbox, const Rect.fromLTWH(1, 2, 3, 4));
    expect(region.type, 'dialogue');
    expect(region.data['custom'], 'keep');
    expect(region.warp?['kind'], 'arc');
    expect(document.strokes.first.mode, Stroke.erase);
    expect(document.strokes.first.radius, 1);
    expect(document.strokes.first.points, [const Offset(1, 2)]);
    expect(document.warnings, ['a', '2']);
    expect(document.toJson()['extra_top'], true);
  });

  test('text_position и bubble_bbox читаются и пишутся независимо от bbox', () {
    final region = Region(<String, dynamic>{
      'id': '1',
      'bbox': [10, 20, 100, 50],
      'bubble_bbox': [8, 18, 104, 54],
      'text_position': [60.5, 45.25],
    });
    expect(region.bbox, const Rect.fromLTWH(10, 20, 100, 50));
    expect(region.bubbleBbox, const Rect.fromLTWH(8, 18, 104, 54));
    expect(region.textPosition, const Offset(60.5, 45.25));
    region.textPosition = const Offset(70, 55);
    expect(region.data['text_position'], [70.0, 55.0]);
    region.textPosition = null;
    expect(region.textPosition, isNull);
  });

  test('blankRegion и nextRegionId', () {
    final document = PageDocument.fromJson(<String, dynamic>{
      'regions': [
        {'id': '2'},
        {'id': '7'},
      ],
    });
    expect(document.nextRegionId(), 8);
    final region = Region(blankRegion(8, const Rect.fromLTWH(5, 5, 2, 2)));
    expect(region.id, '8');
    expect(region.edited, isTrue);
    expect(region.skip, isFalse);
    expect(region.type, 'dialogue');
    expect(region.bbox, const Rect.fromLTWH(5, 5, 2, 2));
  });

  test('clampBox: минимум 4 px и границы листа', () {
    expect(
      clampBox(const Rect.fromLTWH(-10, 3000, 5000, 10), 1000, 2000),
      const Rect.fromLTWH(0, 1990, 1000, 10),
    );
    expect(
      clampBox(const Rect.fromLTWH(10, 10, 1, 1), 1000, 1000),
      const Rect.fromLTWH(10, 10, 4, 4),
    );
  });

  test('addStroke и contentKey без версии', () {
    final document = PageDocument.fromJson(<String, dynamic>{
      'version': 3,
      'regions': <dynamic>[],
    });
    final keyBefore = document.contentKey();
    document.addStroke(
      Stroke(
        mode: Stroke.paint,
        radius: 12,
        points: [const Offset(1, 1), const Offset(2, 2)],
      ),
    );
    expect(document.strokes, hasLength(1));
    final keyAfter = document.contentKey();
    expect(keyAfter, isNot(keyBefore));
    document.version = 9;
    expect(document.contentKey(), keyAfter);
  });

  test('флаги региона: skip/overflow/sfx', () {
    final document = PageDocument.fromJson(<String, dynamic>{
      'regions': [
        {'id': '1', 'skip': true, 'overflow': true},
        {'id': '2', 'type': 'sfx'},
      ],
    });
    expect(document.regions.first.skip, isTrue);
    expect(document.hasOverflow, isTrue);
    expect(document.overflowCount, 1);
    expect(document.regions.last.isSfx, isTrue);
  });
}
