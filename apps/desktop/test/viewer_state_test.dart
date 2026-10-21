import 'dart:convert';
import 'dart:ui' show Offset, Rect, Size;

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';

const _png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ'
    'DwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

Map<String, dynamic> _document({
  int version = 3,
  List<dynamic>? regions,
  List<dynamic>? strokes,
}) => <String, dynamic>{
  'version': version,
  'regions':
      regions ??
      [
        {
          'id': '1',
          'bbox': [10, 10, 100, 100],
          'text': 'hi',
        },
      ],
  'strokes': strokes ?? <dynamic>[],
};

void main() {
  late List<String> requests;
  late List<String> bodies;
  late int status;
  late Map<String, dynamic> Function(String path) handler;

  ViewerState build() {
    final client = MockClient((request) async {
      requests.add('${request.method} ${request.url.path}');
      bodies.add(request.body);
      final payload = handler(request.url.path);
      final code = status;
      status = 200;
      final raw = payload['__bytes'];
      if (raw is List<int>) {
        return http.Response.bytes(raw, code);
      }
      return http.Response(
        jsonEncode(payload),
        code,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    return ViewerState()..bind(
      IltApi(
        ready: const ApiReady(port: 1, token: 't'),
        client: client,
      ),
    );
  }

  setUp(() {
    requests = <String>[];
    bodies = <String>[];
    status = 200;
    handler = (path) => <String, dynamic>{};
  });

  test('openPage загружает документ и версию', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    expect(viewer.document?.version, 3);
    expect(viewer.document?.regions, hasLength(1));
    expect(viewer.selectedRegionId, isNull);
    expect(requests, contains('GET /api/pages/p1'));
    viewer.dispose();
  });

  test('правка-черновик ждёт «Готово», затем PUT с base_version', () async {
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(version: 4),
        };
      }
      if (path == '/api/pages/p1/document') {
        return {'document': _document(version: 5)};
      }
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    final changed = viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 8, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    expect(changed, isTrue);
    expect(viewer.hasDeferredDraft, isTrue);
    expect(viewer.editCount, 1);
    expect(viewer.isDirty('p1'), isTrue);
    // без «Готово» PUT не уходит
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(requests.where((r) => r.startsWith('PUT')), isEmpty);

    handler = (path) {
      if (path == '/api/pages/p1/document') {
        return {'document': _document(version: 5)};
      }
      return <String, dynamic>{};
    };
    viewer.commitDeferredEdits();
    await viewer.whenSaved('p1');
    final puts = <int>[
      for (var i = 0; i < requests.length; i++)
        if (requests[i].startsWith('PUT')) i,
    ];
    expect(puts, hasLength(1));
    final body = jsonDecode(bodies[puts.first]) as Map<String, dynamic>;
    expect(body['base_version'], 4);
    expect((body['document'] as Map)['version'], 4);
    expect(viewer.hasDeferredDraft, isFalse);
    expect(viewer.document?.version, 5);
    viewer.dispose();
  });

  test('409: повторная попытка с версией из ошибки', () async {
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(version: 4),
        };
      }
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 8, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    var puts = 0;
    handler = (path) {
      if (path == '/api/pages/p1/document') {
        puts += 1;
        if (puts == 1) {
          status = 409;
          return {
            'error': 'Конфликт версий',
            'document': _document(version: 9),
          };
        }
        return {'document': _document(version: 10)};
      }
      return <String, dynamic>{};
    };
    viewer.commitDeferredEdits();
    await viewer.whenSaved('p1');
    expect(puts, 2);
    expect(viewer.document?.version, 10);
    final retryIndex = requests.lastIndexOf('PUT /api/pages/p1/document');
    final body = jsonDecode(bodies[retryIndex]) as Map<String, dynamic>;
    expect(body['base_version'], 9);
    expect(viewer.errorText, isNull);
    viewer.dispose();
  });

  test('undo/redo откатывают правки по одной', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(2, 2)]),
      ),
      deferApply: true,
    );
    expect(viewer.document?.strokes, hasLength(2));
    expect(viewer.canUndo, isTrue);
    viewer.undo();
    expect(viewer.document?.strokes, hasLength(1));
    expect(viewer.canRedo, isTrue);
    viewer.redo();
    expect(viewer.document?.strokes, hasLength(2));
    viewer.dispose();
  });

  test('discardDeferredEdits перечитывает серверный документ', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    await viewer.discardDeferredEdits();
    expect(viewer.hasDeferredDraft, isFalse);
    expect(viewer.document?.strokes, isEmpty);
    expect(viewer.canUndo, isFalse);
    viewer.dispose();
  });

  test('createRegion, nudge и delete', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.session.setImageSize(const Size(500, 500));
    viewer.createRegion(const Rect.fromLTWH(20, 20, 50, 40));
    expect(viewer.document?.regions, hasLength(2));
    expect(viewer.selectedRegionId, '2');
    expect(viewer.showBoxes, isTrue);
    viewer.nudgeSelectedRegion('right');
    expect(viewer.document?.regions.last.bbox.left, 21);
    viewer.nudgeSelectedRegion('down', shift: true);
    expect(viewer.document?.regions.last.bbox.top, 30);
    viewer.deleteSelectedRegion();
    expect(viewer.document?.regions, hasLength(1));
    expect(viewer.selectedRegionId, isNull);
    viewer.dispose();
  });

  test('лассо: 3+ точки превращаются в штрих fill', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.session.lassoMode = Stroke.eraseFill;
    viewer.session.addLassoPoint(const Offset(1, 1));
    viewer.session.addLassoPoint(const Offset(5, 1));
    viewer.session.addLassoPoint(const Offset(5, 5));
    expect(viewer.commitLassoDraft(), isTrue);
    expect(viewer.document?.strokes.single.mode, Stroke.eraseFill);
    expect(viewer.document?.strokes.single.points, hasLength(3));
    expect(viewer.session.lasso, isEmpty);
    // меньше трёх точек — черновик просто сбрасывается
    viewer.session.addLassoPoint(const Offset(1, 1));
    expect(viewer.commitLassoDraft(), isFalse);
    viewer.dispose();
  });

  test('заливка добавляет flood-штрих и просит превью', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    requests.clear();
    bodies.clear();
    viewer.floodFill(const Offset(12, 14), Stroke.flood);
    final stroke = viewer.document!.strokes.last;
    expect(stroke.mode, Stroke.flood);
    expect(stroke.points.single, const Offset(12, 14));
    expect(stroke.tolerance, 20);
    await Future<void>.delayed(Duration.zero);
    final index = requests.indexWhere((item) => item.contains('fill-preview'));
    expect(index, isNonNegative);
    final body = jsonDecode(bodies[index]) as Map<String, dynamic>;
    expect(body['x'], 12);
    expect(body['y'], 14);
    expect(body['tolerance'], 20);
    viewer.dispose();
  });

  test('страж ухода: черновик поднимает диалог', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    var ran = false;
    await viewer.guardOrRun(() async {
      ran = true;
    });
    expect(ran, isFalse);
    expect(viewer.leavePromptVisible, isTrue);
    viewer.cancelLeave();
    expect(ran, isFalse);
    await viewer.guardOrRun(() async {
      ran = true;
    });
    await viewer.discardLeave();
    expect(ran, isTrue);
    expect(viewer.hasDeferredDraft, isFalse);
    viewer.dispose();
  });

  test('reloadIfClean не трогает документ с черновиком', () async {
    var version = 3;
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(version: version),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    version = 8;
    await viewer.reloadIfClean('p1');
    expect(viewer.document?.version, 3);
    expect(viewer.document?.strokes, hasLength(1));
    viewer.dispose();
  });

  test('изображения декодируются и кэшируются по видам', () async {
    // 1×1 PNG.
    final png = base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ'
      'DwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    );
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(),
        };
      }
      if (path.contains('/image/')) return {'__bytes': png};
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(viewer.imageFor('result'), isNotNull);
    expect(viewer.imageFor('mask'), isNotNull);
    viewer.setView('original');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(viewer.imageFor('original'), isNotNull);
    expect(requests.where((r) => r.contains('/image/result')).length, 1);
    viewer.setView('clean');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(viewer.imageFor('clean'), isNotNull);
    expect(requests.where((r) => r.contains('/image/clean')).length, 1);
    viewer.dispose();
  });

  test('bakedStrokeCount снимает цвет с сохранённых штрихов', () async {
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(
            version: 3,
            strokes: [
              {
                'mode': 'paint',
                'radius': 4,
                'points': [
                  [1.0, 1.0],
                ],
              },
              {
                'mode': 'erase',
                'radius': 4,
                'points': [
                  [2.0, 2.0],
                ],
              },
            ],
          ),
        };
      }
      if (path == '/api/pages/p1/document') return {'version': 4};
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    expect(viewer.bakedStrokeCount, 2);
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(3, 3)]),
      ),
      deferApply: true,
    );
    expect(viewer.bakedStrokeCount, 2);
    viewer.commitDeferredEdits();
    await viewer.whenSaved('p1');
    expect(viewer.document?.version, 4);
    expect(viewer.bakedStrokeCount, 3);
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(4, 4)]),
      ),
      deferApply: true,
    );
    expect(viewer.bakedStrokeCount, 3);
    viewer.undo();
    expect(viewer.document?.strokes, hasLength(3));
    expect(viewer.bakedStrokeCount, 3);
    viewer.redo();
    expect(viewer.document?.strokes, hasLength(4));
    expect(viewer.bakedStrokeCount, 3);
    viewer.dispose();
  });

  test('смена страницы сбрасывает счётчики версий', () async {
    handler = (path) {
      final pageId = path.split('/').last;
      return {
        'page': {'id': pageId},
        'document': _document(
          version: 3,
          strokes: pageId == 'p1'
              ? [
                  {
                    'mode': 'paint',
                    'radius': 4,
                    'points': [
                      [1.0, 1.0],
                    ],
                  },
                  {
                    'mode': 'paint',
                    'radius': 4,
                    'points': [
                      [2.0, 2.0],
                    ],
                  },
                ]
              : [
                  {
                    'mode': 'erase',
                    'radius': 4,
                    'points': [
                      [3.0, 3.0],
                    ],
                  },
                ],
        ),
      };
    };
    final viewer = build();
    await viewer.openPage('p1');
    expect(viewer.bakedStrokeCount, 2);
    await viewer.openPage('p2');
    expect(viewer.bakedStrokeCount, 1);
    viewer.dispose();
  });

  test('история держит 1000 шагов', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    for (var i = 0; i < 1001; i++) {
      viewer.editDocument(
        (document) => document.addStroke(
          Stroke(mode: Stroke.paint, radius: 4, points: [Offset(i * 1.0, 1)]),
        ),
        deferApply: true,
      );
    }
    expect(viewer.document?.strokes, hasLength(1001));
    for (var i = 0; i < 1000; i++) {
      viewer.undo();
    }
    expect(viewer.document?.strokes, hasLength(1));
    expect(viewer.canUndo, isFalse);
    viewer.dispose();
  });

  test('CanvasSession: панорама с вертикальным запасом ¼', () {
    final session = CanvasSession(onChanged: () {});
    session.setViewport(const Size(300, 300));
    session.setImageSize(const Size(100, 400));
    session.setZoom(1.0);
    expect(session.transform.ty, closeTo(-50, 1e-9));
    // Лист выше вьюпорта: запас 100 px сверху и снизу.
    session.panBy(const Offset(0, 500));
    expect(session.transform.ty, closeTo(100, 1e-9));
    session.panBy(const Offset(0, -2000));
    expect(session.transform.ty, closeTo(-200, 1e-9));
    session.dispose();
  });

  test('CanvasSession: zoomStep и числовой setZoom держат центр', () {
    final session = CanvasSession(onChanged: () {});
    session.setViewport(const Size(300, 300));
    session.setImageSize(const Size(600, 400));
    const center = Offset(150, 150);
    final beforeStep = session.transform.toScene(center);
    session.zoomStep(1);
    expect(session.transform.toScene(center).dx, closeTo(beforeStep.dx, 1e-6));
    expect(session.transform.toScene(center).dy, closeTo(beforeStep.dy, 1e-6));
    final beforeSet = session.transform.toScene(center);
    session.setZoom(1.0);
    expect(session.transform.toScene(center).dx, closeTo(beforeSet.dx, 1e-6));
    expect(session.transform.toScene(center).dy, closeTo(beforeSet.dy, 1e-6));
    session.dispose();
  });

  test('смена страницы: числовой зум стартует сверху (веб-паритет)', () async {
    handler = (path) => {
      'page': {'id': path.split('/').last},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.session.setViewport(const Size(300, 300));
    viewer.session.setImageSize(const Size(100, 800));
    viewer.session.setZoom(1.0);
    viewer.session.panBy(const Offset(0, -400));
    expect(viewer.session.transform.ty, isNot(0));
    await viewer.openPage('p2');
    // Зум сохранён, лист — с верхнего края (веб: pinScroll).
    expect(viewer.session.zoomMode, 1.0);
    expect(viewer.session.transform.scale, closeTo(1.0, 1e-9));
    expect(viewer.session.transform.ty, 0);
    // Перезагрузка той же страницы позицию не сбрасывает.
    viewer.session.panBy(const Offset(0, -120));
    final before = viewer.session.transform.ty;
    expect(before, isNot(0));
    await viewer.openPage('p2');
    expect(viewer.session.transform.ty, before);
    viewer.dispose();
  });

  test('смена страницы: fit остаётся вписанным', () async {
    handler = (path) => {
      'page': {'id': path.split('/').last},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.session.setViewport(const Size(300, 300));
    viewer.session.setImageSize(const Size(100, 800));
    expect(viewer.session.zoomMode, 'fit');
    final scale = viewer.session.transform.scale;
    expect(scale, lessThan(1));
    await viewer.openPage('p2');
    expect(viewer.session.zoomMode, 'fit');
    expect(viewer.session.transform.scale, closeTo(scale, 1e-9));
    viewer.dispose();
  });

  test('applyDeferredEdits: ждёт сохранения и готовый результат', () async {
    var gets = 0;
    handler = (path) {
      if (path == '/api/pages/p1') {
        gets += 1;
        return {
          'page': {'id': 'p1'},
          'status': gets < 4 ? 'running' : 'done',
          'render_version': gets < 4 ? 0 : 5,
          'document': _document(version: 5),
        };
      }
      if (path == '/api/pages/p1/document') {
        return {'document': _document(version: 4), 'plan': 'typeset'};
      }
      if (path == '/api/pages/p1/image/result') {
        return {'__bytes': base64Decode(_png)};
      }
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.setRegionWarpPreset('1', 'wave');
    expect(viewer.hasDeferredDraft, isTrue);
    final ok = await viewer.applyDeferredEdits();
    expect(ok, isTrue);
    expect(viewer.isApplying, isFalse);
    expect(gets, greaterThanOrEqualTo(5));
    expect(viewer.document?.version, 5);
    viewer.dispose();
  });

  test(
    'applyDeferredEdits: ошибка сохранения сохраняет черновик для повтора',
    () async {
      handler = (path) => {
        'page': {'id': 'p1'},
        'document': _document(version: 4),
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.setRegionWarpPreset('1', 'wave');
      var puts = 0;
      handler = (path) {
        if (path == '/api/pages/p1/document') {
          puts += 1;
          if (puts == 1) {
            status = 500;
            return {'error': 'Сбой сохранения'};
          }
          return {'document': _document(version: 4), 'plan': 'typeset'};
        }
        if (path == '/api/pages/p1') {
          return {
            'page': {'id': 'p1'},
            'status': 'done',
            'render_version': 4,
            'document': _document(version: 4),
          };
        }
        if (path == '/api/pages/p1/image/result') {
          return {'__bytes': base64Decode(_png)};
        }
        return <String, dynamic>{};
      };
      expect(await viewer.applyDeferredEdits(), isFalse);
      expect(viewer.hasDeferredDraft, isTrue);
      expect(viewer.applyError, isNotEmpty);
      expect(puts, 1);

      expect(await viewer.applyDeferredEdits(), isTrue);
      expect(puts, 2);
      expect(viewer.hasDeferredDraft, isFalse);
      viewer.dispose();
    },
  );

  test(
    'Done получает свежий layout_snapshot и кладёт его в PUT',
    () async {
      handler = (path) => {
        'page': {'id': 'p1'},
        'document': _document(version: 4),
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.selectRegion('1');
      viewer.document!.regions[0].data['layout_snapshot'] = {
        'version': 1,
        'layout_key': 'old',
        'font_size': 12,
        'lines': [
          ['Old', 0, 0],
        ],
      };
      viewer.setRegionWarpPreset('1', 'wave');
      Object? snapshotRequest;
      handler = (path) {
        if (path == '/api/pages/p1/layout-snapshot') {
          snapshotRequest = jsonDecode(bodies.last);
          return {
            'layout_snapshot': {
              'version': 1,
              'layout_key': 'old',
              'font_size': 12,
              'lines': [
                ['Old', 0, 0],
              ],
            },
          };
        }
        if (path == '/api/pages/p1/document') {
          return {'document': _document(version: 4), 'plan': 'typeset'};
        }
        if (path == '/api/pages/p1') {
          return {
            'page': {'id': 'p1'},
            'status': 'done',
            'render_version': 4,
            'document': _document(version: 4),
          };
        }
        if (path == '/api/pages/p1/image/result') {
          return {'__bytes': base64Decode(_png)};
        }
        return <String, dynamic>{};
      };
      expect(await viewer.applyDeferredEdits(), isTrue);
      final request = snapshotRequest! as Map<String, dynamic>;
      expect((request['draft'] as Map)['layout_snapshot']['font_size'], 12);
      expect(request['drafts'], hasLength(1));
      final index = requests.lastIndexOf('PUT /api/pages/p1/document');
      final body = jsonDecode(bodies[index]) as Map<String, dynamic>;
      final region = (body['document'] as Map)['regions'][0] as Map;
      expect(region['layout_snapshot']['font_size'], 12);
      expect(region['layout_snapshot']['version'], 1);
      viewer.dispose();
    },
  );

  test(
    'Done сохраняет новый регион через drafts в layout-snapshot',
    () async {
      handler = (path) => {
        'page': {'id': 'p1'},
        'document': _document(version: 4, regions: []),
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.session.setImageSize(const Size(500, 500));
      viewer.createRegion(const Rect.fromLTWH(20, 20, 80, 40));
      Object? snapshotRequest;
      handler = (path) {
        if (path == '/api/pages/p1/layout-snapshot') {
          snapshotRequest = jsonDecode(bodies.last);
          return {
            'layout_snapshot': {
              'version': 1,
              'layout_key': 'new',
              'font_size': 16,
              'lines': [
                ['Новый', 0, 0],
              ],
            },
          };
        }
        if (path == '/api/pages/p1/document') {
          return {'document': _document(version: 4, regions: []), 'plan': 'typeset'};
        }
        if (path == '/api/pages/p1') {
          return {
            'page': {'id': 'p1'},
            'status': 'done',
            'render_version': 4,
            'document': _document(version: 4, regions: []),
          };
        }
        if (path == '/api/pages/p1/image/result') {
          return {'__bytes': base64Decode(_png)};
        }
        return <String, dynamic>{};
      };
      expect(await viewer.applyDeferredEdits(), isTrue);
      final request = snapshotRequest! as Map<String, dynamic>;
      final drafts = request['drafts'] as List;
      expect(drafts, hasLength(1));
      expect('${drafts.first['id']}', '1');
      final putIndex = requests.lastIndexOf('PUT /api/pages/p1/document');
      final body = jsonDecode(bodies[putIndex]) as Map<String, dynamic>;
      expect((body['document'] as Map)['regions'], hasLength(1));
      viewer.dispose();
    },
  );

  test(
    'applyDeferredEdits: после ошибки bake повтор запускает rebake без нового PUT',
    () async {
      handler = (path) => {
        'page': {'id': 'p1'},
        'document': _document(version: 4),
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.selectRegion('1');
      viewer.setRegionWarpPreset('1', 'wave');
      var puts = 0;
      var rebakes = 0;
      handler = (path) {
        if (path == '/api/pages/p1/document') {
          puts += 1;
          return {'document': _document(version: 4), 'plan': 'typeset'};
        }
        if (path == '/api/pages/p1/rebake') {
          rebakes += 1;
          return {'job_id': 'again'};
        }
        if (path == '/api/pages/p1') {
          if (rebakes == 0) {
            return {
              'page': {'id': 'p1'},
              'status': 'error',
              'error': 'Не собралось',
              'render_version': 0,
              'document': _document(version: 4),
            };
          }
          return {
            'page': {'id': 'p1'},
            'status': 'done',
            'render_version': 4,
            'document': _document(version: 4),
          };
        }
        if (path == '/api/pages/p1/image/result') {
          return {'__bytes': base64Decode(_png)};
        }
        return <String, dynamic>{};
      };
      expect(await viewer.applyDeferredEdits(), isFalse);
      expect(viewer.hasDeferredDraft, isTrue);
      expect(puts, 1);
      expect(rebakes, 0);

      expect(await viewer.applyDeferredEdits(), isTrue);
      expect(puts, 1);
      expect(rebakes, 1);
      expect(viewer.hasDeferredDraft, isFalse);
      viewer.dispose();
    },
  );

  test(
    'applyDeferredEdits: результат не декодировался — preview остаётся',
    () async {
      handler = (path) {
        if (path == '/api/pages/p1/preview-region') {
          return {'__bytes': base64Decode(_png)};
        }
        return {
          'page': {'id': 'p1'},
          'document': _document(version: 4),
        };
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.selectRegion('1');
      await Future<void>.delayed(const Duration(milliseconds: 500));
      expect(viewer.stylePreviewImage, isNotNull);
      viewer.editDocument(
        (document) => document.addStroke(
          const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
        ),
        deferApply: true,
      );
      var badImage = true;
      handler = (path) {
        if (path == '/api/pages/p1/document') {
          return {
            'document': _document(version: 4, strokes: []),
            'plan': 'typeset',
          };
        }
        if (path == '/api/pages/p1') {
          return {
            'page': {'id': 'p1'},
            'status': 'done',
            'render_version': 4,
            'document': _document(version: 4, strokes: []),
          };
        }
        if (path == '/api/pages/p1/image/result') {
          return {
            '__bytes': badImage ? <int>[1, 2, 3] : base64Decode(_png),
          };
        }
        return <String, dynamic>{};
      };
      expect(await viewer.applyDeferredEdits(), isFalse);
      expect(viewer.hasDeferredDraft, isTrue);
      expect(viewer.stylePreviewImage, isNotNull);
      expect(viewer.applyError, isNotEmpty);

      badImage = false;
      expect(await viewer.applyDeferredEdits(), isTrue);
      expect(viewer.hasDeferredDraft, isFalse);
      expect(viewer.stylePreviewImage, isNull);
      viewer.dispose();
    },
  );

  test('CanvasSession: cancelGesture отменяет жест и чистит preview', () {
    final session = CanvasSession(onChanged: () {});
    var called = 0;
    session.onCancelGesture = () {
      called += 1;
      return true;
    };
    session.setPreviewRect('1', const Rect.fromLTWH(1, 2, 3, 4));
    expect(session.cancelGesture(), isTrue);
    expect(called, 1);
    expect(session.previewRect, isNull);
    session.onCancelGesture = () => false;
    expect(session.cancelGesture(), isFalse);
    session.dispose();
  });
}
