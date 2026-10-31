import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';

const _png =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ'
    'DwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

Map<String, dynamic> _doc() => <String, dynamic>{
  'version': 3,
  'regions': [
    {
      'id': '1',
      'bbox': [10, 10, 100, 100],
      'text': 'HI',
      'translation': 'ПРИВЕТ',
      'style': {
        'font_size_override': 18,
        'warp': {
          'version': 2,
          'kind': 'mesh',
          'bend': 0.0,
          'quad': null,
          'mesh': [
            for (var row = 0; row < 4; row++)
              for (var col = 0; col < 4; col++) [col * 100 / 3, row * 100 / 3],
          ],
        },
      },
    },
  ],
  'strokes': <dynamic>[],
};

void main() {
  test('mesh: локальный слой готовится один раз и не пересобирается', () async {
    final requests = <String>[];
    final modes = <String>[];
    final client = MockClient((request) async {
      requests.add('${request.method} ${request.url.path}');
      if (request.url.path == '/api/pages/a') {
        return http.Response(
          jsonEncode({
            'page': {'id': 'a'},
            'document': _doc(),
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path == '/api/pages/a/preview-region') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        modes.add('${body['mode'] ?? 'exact'}');
        return http.Response.bytes(
          base64Decode(_png),
          200,
          headers: {
            'content-type': 'image/png',
            'x-offset-x': '10',
            'x-offset-y': '12',
            'x-layer-anchor-x': '60',
            'x-layer-anchor-y': '60',
            'x-layout-snapshot': base64Encode(
              utf8.encode(
                jsonEncode({
                  'version': 1,
                  'layout_key': 'k',
                  'font_size': 18,
                  'lines': [
                    ['HI', 10, 20],
                  ],
                }),
              ),
            ),
          },
        );
      }
      return http.Response('{}', 200);
    });
    final viewer = ViewerState()
      ..bind(
        IltApi(
          ready: const ApiReady(port: 1, token: 't'),
          client: client,
        ),
      );
    addTearDown(viewer.dispose);
    await viewer.openPage('a');
    viewer.selectRegion('1');
    expect(viewer.stylePreviewStatus, 'loading-local');
    await Future<void>.delayed(const Duration(milliseconds: 500));
    expect(modes, containsAll(<String>['base-page', 'base-layer']));
    expect(viewer.stylePreviewStatus, 'ready-local');
    expect(viewer.hasLocalPreview, isTrue);
    expect(viewer.document?.regions.first.data['layout_snapshot'], isNotNull);
    final before = requests
        .where((item) => item == 'POST /api/pages/a/preview-region')
        .length;

    viewer.setRegionWarpBend('1', 0.5);
    await Future<void>.delayed(const Duration(milliseconds: 600));
    final after = requests
        .where((item) => item == 'POST /api/pages/a/preview-region')
        .length;
    expect(after, before);
    expect(viewer.hasLocalPreview, isTrue);

    viewer.setRegionTranslation('1', 'НОВЫЙ');
    await Future<void>.delayed(const Duration(milliseconds: 600));
    final changed = requests
        .where((item) => item == 'POST /api/pages/a/preview-region')
        .length;
    expect(changed, after + 3);
    expect(viewer.hasLocalPreview, isTrue);
  });

  test(
    'поворот без warp: локальный слой после вкладки «Трансформация»',
    () async {
      final requests = <String>[];
      final modes = <String>[];
      final doc = _doc();
      (doc['regions'] as List).first['style'] = <String, dynamic>{
        'font_size_override': 18,
      };
      final client = MockClient((request) async {
        requests.add('${request.method} ${request.url.path}');
        if (request.url.path == '/api/pages/a') {
          return http.Response(
            jsonEncode({
              'page': {'id': 'a'},
              'document': doc,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/api/pages/a/preview-region') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          modes.add('${body['mode'] ?? 'exact'}');
          return http.Response.bytes(
            base64Decode(_png),
            200,
            headers: {
              'content-type': 'image/png',
              'x-offset-x': '10',
              'x-offset-y': '12',
              'x-layer-anchor-x': '60',
              'x-layer-anchor-y': '60',
            },
          );
        }
        return http.Response('{}', 200);
      });
      final viewer = ViewerState()
        ..bind(
          IltApi(
            ready: const ApiReady(port: 1, token: 't'),
            client: client,
          ),
        );
      addTearDown(viewer.dispose);
      await viewer.openPage('a');
      viewer.selectRegion('1');
      await Future<void>.delayed(const Duration(milliseconds: 600));
      expect(modes, contains('exact'));

      viewer.prepareLocalPreview('1');
      await Future<void>.delayed(const Duration(milliseconds: 600));
      expect(modes, containsAll(<String>['base-page', 'base-layer']));
      expect(viewer.hasLocalPreview, isTrue);
      final before = requests
          .where((item) => item == 'POST /api/pages/a/preview-region')
          .length;

      viewer.setRegionRotation('1', 35);
      await Future<void>.delayed(const Duration(milliseconds: 600));
      expect(
        requests
            .where((item) => item == 'POST /api/pages/a/preview-region')
            .length,
        before,
      );
      expect(viewer.hasLocalPreview, isTrue);
    },
  );

  test(
    'geometry change before the debounce still prepares the layer',
    () async {
      final modes = <String>[];
      final client = MockClient((request) async {
        if (request.url.path == '/api/pages/a') {
          return http.Response(
            jsonEncode({
              'page': {'id': 'a'},
              'document': _doc(),
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/api/pages/a/preview-region') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          modes.add('${body['mode'] ?? 'exact'}');
          return http.Response.bytes(
            base64Decode(_png),
            200,
            headers: {
              'content-type': 'image/png',
              'x-offset-x': '10',
              'x-offset-y': '12',
              'x-layer-anchor-x': '60',
              'x-layer-anchor-y': '60',
            },
          );
        }
        return http.Response('{}', 200);
      });
      final viewer = ViewerState()
        ..bind(
          IltApi(
            ready: const ApiReady(port: 1, token: 't'),
            client: client,
          ),
        );
      addTearDown(viewer.dispose);
      await viewer.openPage('a');
      viewer.selectRegion('1');
      viewer.setRegionWarpBend('1', 0.25);
      await Future<void>.delayed(const Duration(milliseconds: 700));
      expect(modes, containsAll(<String>['base-page', 'base-layer']));
      expect(viewer.stylePreviewStatus, 'ready-local');
      expect(viewer.hasLocalPreview, isTrue);
    },
  );

  test('Done saves the frozen layout snapshot from preview', () async {
    final puts = <String>[];
    final doc = _doc();
    final snapshot = {
      'version': 1,
      'layout_key': 'k',
      'font_size': 18,
      'lines': [
        ['HI', 10, 20],
      ],
    };
    final client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/api/pages/a') {
        return http.Response(
          jsonEncode({
            'page': {'id': 'a'},
            'status': 'done',
            'render_version': 4,
            'document': {...doc, 'version': 4},
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (path == '/api/pages/a/document') {
        puts.add(request.body);
        return http.Response(
          jsonEncode({
            'document': {...doc, 'version': 4},
            'plan': 'typeset',
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (path == '/api/pages/a/image/result') {
        return http.Response.bytes(base64Decode(_png), 200);
      }
      if (path == '/api/pages/a/preview-region') {
        return http.Response.bytes(
          base64Decode(_png),
          200,
          headers: {
            'content-type': 'image/png',
            'x-offset-x': '10',
            'x-offset-y': '12',
            'x-layer-anchor-x': '60',
            'x-layer-anchor-y': '60',
            'x-layout-snapshot': base64Encode(
              utf8.encode(jsonEncode(snapshot)),
            ),
          },
        );
      }
      return http.Response('{}', 200);
    });
    final viewer = ViewerState()
      ..bind(
        IltApi(
          ready: const ApiReady(port: 1, token: 't'),
          client: client,
        ),
      );
    addTearDown(viewer.dispose);
    await viewer.openPage('a');
    viewer.selectRegion('1');
    await Future<void>.delayed(const Duration(milliseconds: 500));
    expect(viewer.stylePreviewStatus, 'ready-local');
    viewer.setRegionWarpBend('1', 0.5);
    expect(await viewer.applyDeferredEdits(), isTrue);
    expect(puts, hasLength(1));
    final body = jsonDecode(puts.single) as Map<String, dynamic>;
    final saved = (body['document'] as Map)['regions'] as List;
    final region = saved.first as Map;
    expect(region['layout_snapshot'], isA<Map>());
    expect((region['layout_snapshot'] as Map)['version'], 1);
  });

  test(
    'arc with rotation uses a pre-rotated layer and re-prepares on angle',
    () async {
      final doc = _doc();
      (doc['regions'] as List).first['style'] = <String, dynamic>{
        'font_size_override': 18,
        'rotation': 35.0,
        'warp': {
          'version': 2,
          'kind': 'arc',
          'bend': 0.35,
          'quad': null,
          'mesh': null,
        },
      };
      final previews = <Map<String, dynamic>>[];
      final client = MockClient((request) async {
        if (request.url.path == '/api/pages/a') {
          return http.Response(
            jsonEncode({
              'page': {'id': 'a'},
              'document': doc,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/api/pages/a/preview-region') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          if (body['mode'] == 'base-layer') previews.add(body);
          return http.Response.bytes(
            base64Decode(_png),
            200,
            headers: {
              'content-type': 'image/png',
              'x-offset-x': '10',
              'x-offset-y': '12',
              'x-layer-anchor-x': '60',
              'x-layer-anchor-y': '60',
            },
          );
        }
        return http.Response('{}', 200);
      });
      final viewer = ViewerState()
        ..bind(
          IltApi(
            ready: const ApiReady(port: 1, token: 't'),
            client: client,
          ),
        );
      addTearDown(viewer.dispose);
      await viewer.openPage('a');
      viewer.selectRegion('1');
      viewer.prepareLocalPreview('1');
      await Future<void>.delayed(const Duration(milliseconds: 700));
      expect(viewer.stylePreviewStatus, 'ready-local');
      expect(previews, isNotEmpty);
      expect(previews.last['apply_rotation'], isTrue);

      final before = previews.length;
      viewer.setRegionRotation('1', 50);
      await Future<void>.delayed(const Duration(milliseconds: 700));
      expect(previews.length, before + 1);
      expect(previews.last['apply_rotation'], isTrue);
      expect(viewer.hasLocalPreview, isTrue);
    },
  );
}
