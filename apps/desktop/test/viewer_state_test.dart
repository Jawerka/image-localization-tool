import 'dart:convert';
import 'dart:ui' show Offset, Rect, Size;

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';

Map<String, dynamic> _document({
  int version = 3,
  List<dynamic>? regions,
  List<dynamic>? strokes,
}) =>
    <String, dynamic>{
      'version': version,
      'regions': regions ??
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
    return ViewerState()
      ..bind(IltApi(ready: const ApiReady(port: 1, token: 't'), client: client));
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
        return {'page': {'id': 'p1'}, 'document': _document(version: 4)};
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
        return {'page': {'id': 'p1'}, 'document': _document(version: 4)};
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
        return {'page': {'id': 'p1'}, 'document': _document()};
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
    expect(
      requests.where((r) => r.contains('/image/result')).length,
      1,
    );
    viewer.dispose();
  });

  test('CanvasSession: панорама с вертикальным запасом ¼', () {
    final session = CanvasSession(onChanged: () {});
    session.setViewport(const Size(300, 300));
    session.setImageSize(const Size(100, 400));
    session.setZoom(1.0);
    expect(session.transform.ty, 0);
    // Лист выше вьюпорта: запас 100 px сверху и снизу.
    session.panBy(const Offset(0, 500));
    expect(session.transform.ty, closeTo(100, 1e-9));
    session.panBy(const Offset(0, -2000));
    expect(session.transform.ty, closeTo(-200, 1e-9));
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
    expect(viewer.session.transform.ty, 0);
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
}
