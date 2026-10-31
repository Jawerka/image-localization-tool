import 'dart:convert';
import 'dart:ui' show Offset, Rect;

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';

Map<String, dynamic> _document({int version = 3, List<dynamic>? regions}) =>
    <String, dynamic>{
      'version': version,
      'regions':
          regions ??
          [
            {
              'id': '1',
              'bbox': [10, 10, 100, 100],
              'text': 'hi',
              'translation': '',
            },
            {
              'id': '2',
              'bbox': [200, 200, 80, 60],
              'text': 'GRRRRR',
              'type': 'sfx',
              'block_type': 'sfx',
              'translation': 'РРРРР',
            },
          ],
      'strokes': <dynamic>[],
    };

void main() {
  late List<String> requests;
  late List<String> bodies;
  late List<Map<String, String>> headerSets;
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
      final headers = <String, String>{
        'content-type': 'application/json; charset=utf-8',
        ...?payload['__headers'] is Map
            ? (payload['__headers'] as Map).cast<String, String>()
            : null,
      };
      headerSets.add(headers);
      if (raw is List<int>) {
        return http.Response.bytes(raw, code, headers: headers);
      }
      return http.Response(jsonEncode(payload), code, headers: headers);
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
    headerSets = <Map<String, String>>[];
    status = 200;
    handler = (path) => <String, dynamic>{};
  });

  test('текст: пауза 500 мс, коалесинг, translation_locked', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.setRegionText('1', 'he');
    expect(requests.where((r) => r.startsWith('PUT')), isEmpty);
    viewer.setRegionText('1', 'hello');
    await viewer.whenSaved('p1');
    final puts = requests.where((r) => r.startsWith('PUT')).toList();
    expect(puts, hasLength(1));
    final body =
        jsonDecode(bodies[requests.indexOf(puts.first)])
            as Map<String, dynamic>;
    final region =
        ((body['document'] as Map)['regions'] as List).first
            as Map<String, dynamic>;
    expect(region['text'], 'hello');
    // коалесинг: одна запись истории на серию
    expect(viewer.canUndo, isTrue);
    viewer.undo();
    expect(viewer.document!.findRegion('1')!.data['text'], 'hi');
    viewer.dispose();
  });

  test('translation_locked следует за непустым переводом', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.setRegionTranslation('1', 'привет');
    expect(viewer.document!.findRegion('1')!.data['translation_locked'], true);
    viewer.setRegionTranslation('1', '  ');
    expect(viewer.document!.findRegion('1')!.data['translation_locked'], false);
    viewer.dispose();
  });

  test('тип и говорящий: немедленное сохранение без паузы', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.setRegionType('1', 'thought');
    viewer.setRegionSpeaker('1', 'Кирби');
    await Future<void>.delayed(const Duration(milliseconds: 600));
    final puts = requests.where((r) => r.startsWith('PUT')).toList();
    expect(puts, hasLength(1));
    final body =
        jsonDecode(bodies[requests.indexOf(puts.first)])
            as Map<String, dynamic>;
    final region =
        ((body['document'] as Map)['regions'] as List).first
            as Map<String, dynamic>;
    expect(region['type'], 'thought');
    expect(region['block_type'], 'thought');
    expect(region['speaker'], 'Кирби');
    viewer.dispose();
  });

  test('стиль: черновик, пресеты, кламп кегля, счётчик пилюли', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.setFontBounds(10, 64);
    // текстовое автосохранение в счётчик черновика не входит
    viewer.setRegionText('1', 'hello');
    await viewer.whenSaved('p1');
    viewer.setRegionWarpPreset('1', 'arc-up');
    expect(viewer.hasDeferredDraft, isTrue);
    expect(viewer.editCount, 1);
    expect(requests.where((r) => r.startsWith('PUT')), hasLength(1));
    final style = viewer.document!.findRegion('1')!.styleMap();
    expect(style['warp']['kind'], 'arc');
    expect(style['warp']['bend'], 0.35);

    viewer.setRegionWarpBend('1', 0.5);
    viewer.setRegionWarpBend('1', 0.7);
    expect(viewer.editCount, 2); // коалесинг серии bend

    viewer.setRegionFontSize('1', 200);
    expect(
      viewer.document!.findRegion('1')!.styleMap()['font_size_override'],
      64,
    );
    viewer.setRegionFontSize('1', 0);
    expect(
      viewer.document!.findRegion('1')!.styleMap()['font_size_override'],
      0,
    );

    viewer.commitDeferredEdits();
    await viewer.whenSaved('p1');
    expect(viewer.hasDeferredDraft, isFalse);
    expect(viewer.editCount, 0);
    viewer.dispose();
  });

  test('text_position: независимый якорь, сброс и режим перемещения', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(
        regions: [
          {
            'id': '1',
            'bbox': [10, 10, 100, 100],
            'bubble_bbox': [0, 0, 120, 120],
            'text': 'hi',
            'translation': '',
          },
        ],
      ),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.selectRegion('1');
    final region = viewer.document!.findRegion('1')!;
    expect(viewer.textAnchorFor(region), const Offset(60, 60));
    viewer.setTextPosition('1', const Offset(80, 90));
    final moved = viewer.document!.findRegion('1')!;
    expect(moved.textPosition, const Offset(80, 90));
    expect(moved.bbox, const Rect.fromLTWH(10, 10, 100, 100));
    expect(viewer.hasDeferredDraft, isTrue);
    viewer.resetTextPosition('1');
    expect(viewer.document!.findRegion('1')!.textPosition, isNull);
    viewer.toggleTextMove('1');
    expect(viewer.isTextMoveActive('1'), isTrue);
    viewer.selectRegion('2');
    expect(viewer.isTextMoveActive('1'), isFalse);
    viewer.dispose();
  });

  test('clipboard стиля: копировать/вставить, warp слиянием', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.selectRegion('1');
    viewer.setRegionWarpPreset('1', 'wave');
    viewer.setRegionFillRgb('1', [255, 0, 0]);
    viewer.copyStyle();
    expect(viewer.hasStyleClipboard, isTrue);
    viewer.selectRegion('2');
    expect(viewer.pasteStyle(), isTrue);
    final target = viewer.document!.findRegion('2')!.styleMap();
    expect(target['fill_rgb'], [255, 0, 0]);
    expect(target['warp']['kind'], 'wave');
    viewer.dispose();
  });

  test('skip сохраняется сразу, delete идёт в черновик', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.toggleRegionSkip('1');
    // локально флаг виден до ответа сервера
    expect(viewer.document!.findRegion('1')!.skip, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(requests.where((r) => r.startsWith('PUT')), hasLength(1));
    final index = requests.indexOf('PUT /api/pages/p1/document');
    final body = jsonDecode(bodies[index]) as Map<String, dynamic>;
    final region =
        ((body['document'] as Map)['regions'] as List).first
            as Map<String, dynamic>;
    expect(region['skip'], true);

    viewer.selectRegion('1');
    viewer.deleteRegion('1');
    expect(viewer.document!.regions, hasLength(1));
    expect(viewer.selectedRegionId, isNull);
    expect(viewer.hasDeferredDraft, isTrue);
    viewer.dispose();
  });

  test('действие региона: тело запроса и сброс состояния ожидания', () async {
    handler = (path) => {
      'page': {'id': 'p1'},
      'document': _document(),
    };
    final viewer = build();
    await viewer.openPage('p1');
    await viewer.regionAction('2', 'shorten');
    expect(requests, contains('POST /api/pages/p1/action'));
    final index = requests.indexOf('POST /api/pages/p1/action');
    final body = jsonDecode(bodies[index]) as Map<String, dynamic>;
    expect(body['action'], 'shorten');
    expect(body['region_id'], '2');
    expect(viewer.actionPending, isFalse);
    viewer.dispose();
  });

  test(
    'sfx: подбор стиля применяет черновик и перечитывает документ',
    () async {
      var version = 3;
      handler = (path) {
        if (path == '/api/pages/p1') {
          return {
            'page': {'id': 'p1'},
            'document': _document(
              version: version,
              regions: [
                {
                  'id': '2',
                  'bbox': [200, 200, 80, 60],
                  'type': 'sfx',
                  'translation': 'РРРРР',
                  'style': {
                    'font_id': 'unsightly',
                    'fill_rgb': [17, 17, 17],
                  },
                },
              ],
            ),
          };
        }
        return <String, dynamic>{};
      };
      final viewer = build();
      await viewer.openPage('p1');
      viewer.setRegionText('2', 'новый');
      await viewer.restyleSfx('2');
      expect(requests, contains('POST /api/pages/p1/regions/2/sfx-style'));
      // черновик применён одним PUT до подбора
      expect(requests.where((r) => r.startsWith('PUT')), isNotEmpty);
      expect(viewer.sfxStatus, 'ready');
      expect(
        viewer.document!.findRegion('2')!.styleMap()['font_id'],
        'unsightly',
      );
      expect(viewer.hasDeferredDraft, isFalse);
      viewer.dispose();
    },
  );

  test('reset страницы очищает историю и перечитывает документ', () async {
    var version = 3;
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(version: version),
        };
      }
      if (path == '/api/pages/p1/reset') {
        version = 9;
        return <String, dynamic>{'ok': true};
      }
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: []),
      ),
      deferApply: true,
    );
    expect(viewer.canUndo, isTrue);
    await viewer.resetPage();
    expect(requests, contains('POST /api/pages/p1/reset'));
    expect(viewer.document!.version, 9);
    expect(viewer.canUndo, isFalse);
    expect(viewer.hasDeferredDraft, isFalse);
    viewer.dispose();
  });

  test('шрифты и стили проекта загружаются, стиль сохраняется PUT', () async {
    handler = (path) {
      if (path == '/api/pages/p1') {
        return {
          'page': {'id': 'p1'},
          'document': _document(),
        };
      }
      if (path == '/api/fonts') {
        return {
          'fonts': [
            {'id': 'heroika', 'family': 'Heroika', 'cyrillic': true},
          ],
        };
      }
      if (path == '/api/project/styles') return <String, dynamic>{};
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    await viewer.ensureFonts();
    expect(viewer.fonts, hasLength(1));
    expect(viewer.fonts.first['family'], 'Heroika');

    var stylesPut = 0;
    handler = (path) {
      if (path == '/api/project/styles') {
        if (stylesPut > 0) {
          return {
            'styles': [
              {
                'name': 'Стиль 1',
                'style': {
                  'fill_rgb': [0, 0, 0],
                },
              },
            ],
          };
        }
        return {
          'styles': [
            {
              'name': 'Крик',
              'style': {'uppercase': true},
            },
          ],
        };
      }
      return <String, dynamic>{};
    };
    await viewer.ensureStyles('pr1');
    expect(viewer.styleLibrary, hasLength(1));
    expect(viewer.styleLibrary.first['name'], 'Крик');

    viewer.selectRegion('1');
    viewer.applyStyleToRegion('1', {'uppercase': true});
    expect(viewer.document!.findRegion('1')!.styleMap()['uppercase'], true);

    stylesPut += 1;
    final saved = await viewer.saveProjectStyle();
    expect(saved, isTrue);
    expect(viewer.styleLibrary, hasLength(1));
    expect(viewer.styleLibrary.first['name'], 'Стиль 1');
    viewer.dispose();
  });

  test('предпросмотр: снимок приходит с offset и очищается', () async {
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
      if (path == '/api/pages/p1/preview-region') {
        return {
          '__bytes': png,
          '__headers': {'x-offset-x': '12', 'x-offset-y': '34'},
        };
      }
      return <String, dynamic>{};
    };
    final viewer = build();
    await viewer.openPage('p1');
    viewer.selectRegion('1');
    expect(viewer.stylePreviewStatus, 'loading');
    await Future<void>.delayed(const Duration(milliseconds: 600));
    expect(viewer.stylePreviewStatus, 'ready');
    expect(viewer.stylePreviewImage, isNotNull);
    expect(viewer.stylePreviewOffset.dx, 12);
    expect(viewer.stylePreviewOffset.dy, 34);
    viewer.selectRegion(null);
    expect(viewer.stylePreviewImage, isNull);
    expect(viewer.stylePreviewStatus, 'idle');
    viewer.dispose();
  });
}
