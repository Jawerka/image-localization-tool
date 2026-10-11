import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/secondary_state.dart';

class _Sent {
  _Sent(this.method, this.path, this.body);

  final String method;
  final String path;
  final String body;
}

SecondaryState _state(
  Map<String, dynamic> Function(String path) reply,
  List<_Sent> sent,
) {
  final client = MockClient((request) async {
    sent.add(_Sent(request.method, request.url.path, request.body));
    return http.Response(
      jsonEncode(reply(request.url.path)),
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  });
  final state = SecondaryState();
  state.bind(IltApi(
    ready: const ApiReady(port: 1111, token: 'tok'),
    client: client,
  ));
  return state;
}

void main() {
  test('модели: статус и прогресс загрузки', () async {
    final ws = _state((path) {
      if (path == '/api/models') {
        return {
          'detector': {'present': true, 'path': r'D:\m\detector.onnx'},
          'lama': {'present': false, 'path': r'D:\m\lama.onnx'},
          'font': {'present': false, 'path': r'D:\m\font.ttf'},
        };
      }
      return {};
    }, []);
    await ws.refreshModels();
    expect(ws.model('detector').present, isTrue);
    expect(ws.model('lama').present, isFalse);
    expect(ws.allModelsPresent, isFalse);
    expect(ws.models.length, 3);

    ws.applyModelProgress({
      'kind': 'lama',
      'done_bytes': 50,
      'total_bytes': 200,
    });
    final lama = ws.model('lama');
    expect(lama.downloading, isTrue);
    expect(lama.percent, closeTo(0.25, 0.001));
    ws.applyModelProgress({
      'kind': 'lama',
      'done_bytes': 200,
      'total_bytes': 200,
    });
    expect(ws.model('lama').percent, 1.0);
  });

  test('startDownload шлёт POST и помечает «готово»', () async {
    final sent = <_Sent>[];
    final ws = _state((path) => {'ok': true}, sent);
    ws.startDownload('detector');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(sent.single.method, 'POST');
    expect(sent.single.path, '/api/models/download');
    expect(sent.single.body, contains('detector'));
    expect(ws.model('detector').present, isTrue);
  });

  test('компоненты: статус, прогресс, скачивание и удаление', () async {
    final sent = <_Sent>[];
    final ws = _state((path) {
      if (path == '/api/runtime') {
        return {
          'platform': 'win',
          'packs': [
            {
              'id': 'torch-cu128',
              'title': 'CUDA',
              'kind': 'torch',
              'size_bytes': 1000,
              'state': 'available',
              'recommended': true,
            },
            {
              'id': 'argos',
              'title': 'Argos',
              'kind': 'argos',
              'size_bytes': 500,
              'state': 'installed',
              'installed_bytes': 600,
            },
          ],
          'hardware': {
            'vendor': 'nvidia',
            'name': 'RTX 5060',
            'driver': 617,
            'recommended': 'torch-cu128',
            'reason': 'CUDA доступна',
          },
          'torch_ready': false,
          'argos_ready': true,
          'device_effective': 'cpu',
        };
      }
      return {'ok': true};
    }, sent);

    await ws.refreshRuntime();
    expect(ws.runtime.packs.length, 2);
    expect(ws.runtime.pack('argos')!.installed, isTrue);
    expect(ws.runtime.pack('torch-cu128')!.recommended, isTrue);
    expect(ws.runtime.deviceEffective, 'cpu');
    expect(ws.runtime.argosReady, isTrue);

    ws.applyRuntimeProgress({
      'id': 'torch-cu128',
      'state': 'downloading',
      'done': 250,
      'total': 1000,
    });
    final downloading = ws.runtime.pack('torch-cu128')!;
    expect(downloading.downloading, isTrue);
    expect(downloading.percent, closeTo(0.25, 0.001));

    ws.applyRuntimeProgress({
      'id': 'torch-cu128',
      'state': 'error',
      'error': 'сеть',
    });
    expect(ws.runtime.pack('torch-cu128')!.failed, isTrue);

    ws.startRuntimeDownload('torch-cu128');
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(sent.last.path, '/api/runtime/download');
    expect(sent.last.body, contains('torch-cu128'));

    await ws.removeRuntimePack('argos');
    expect(sent.last.path, '/api/runtime/remove');
    expect(ws.runtime.pack('argos')!.installed, isFalse);
  });

  test('удалёнка: статус, код сопряжения, отзыв', () async {
    final sent = <_Sent>[];
    final ws = _state((path) {
      switch (path) {
        case '/api/remote/status':
          return {
            'enabled': true,
            'addresses': ['192.168.88.42:8741'],
            'pairing_code': '',
            'devices': [
              {'id': 'd1', 'name': 'iPad · Safari', 'address': 'x', 'active': true},
            ],
            'clients': 1,
          };
        case '/api/remote/pair-code':
          return {
            'enabled': true,
            'addresses': ['192.168.88.42:8741'],
            'pairing_code': '482913',
            'devices': [],
            'clients': 0,
          };
        case '/api/remote/revoke':
          return {
            'enabled': true,
            'addresses': [],
            'pairing_code': '',
            'devices': [],
            'clients': 0,
          };
      }
      return {};
    }, sent);
    await ws.refreshRemote();
    expect(ws.remote.enabled, isTrue);
    expect(ws.remote.devices.single.name, 'iPad · Safari');
    await ws.issuePairCode();
    expect(ws.remote.pairingCode, '482913');
    await ws.revokeDevice('d1');
    expect(sent.last.path, '/api/remote/revoke');
    expect(sent.last.body, contains('d1'));
    expect(ws.remote.devices, isEmpty);
  });

  test('глоссарий: загрузка, сохранение без пустых строк', () async {
    final sent = <_Sent>[];
    final ws = _state((path) {
      if (path == '/api/project/glossary') {
        return {
          'glossary': [
            {'source': 'Alice', 'target': 'Алиса', 'gender': 'f', 'note': 'гл.'},
          ],
        };
      }
      return {};
    }, sent);
    await ws.loadGlossary();
    expect(ws.glossary.single.source, 'Alice');
    await ws.saveGlossary(const [
      GlossaryRow(source: 'Alice', target: 'Алиса'),
      GlossaryRow(source: '', target: 'мусор'),
    ]);
    expect(sent.last.method, 'PUT');
    expect(sent.last.path, '/api/project/glossary');
    expect(sent.last.body, contains('Alice'));
    expect(sent.last.body, isNot(contains('мусор')));
  });

  test('экспорт: папка регистрируется, задание уходит, итог применяется',
      () async {
    final sent = <_Sent>[];
    final ws = _state((path) {
      if (path == '/api/dialog/directory') return {'path': r'D:\out'};
      if (path == '/api/jobs/export') return {'job_id': 'e1'};
      return {};
    }, sent);
    var opened = '';
    ws.onOpenFolder = (path) => opened = path;
    final ok = await ws.registerExportFolder(r'D:\out');
    expect(ok, isTrue);
    expect(sent.first.path, '/api/dialog/directory');
    final dirBody = jsonDecode(sent.first.body) as Map<String, dynamic>;
    expect(dirBody['path'], r'D:\out');

    await ws.runExport(const ExportOptions(
      pageIds: ['a', 'b'],
      dest: r'D:\out',
      format: 'png',
      conflict: 'rename',
      openAfter: true,
    ));
    expect(sent.last.path, '/api/jobs/export');
    expect(sent.last.body, contains('"page_ids":["a","b"]'));

    ws.applyJobFinished({
      'kind': 'export',
      'saved': 2,
      'paths': [r'D:\out\001.png', r'D:\out\002.png'],
    });
    expect(ws.lastExport?.saved, 2);
    expect(opened, r'D:\out');
  });

  test('ошибка API видна в errorText и сбрасывается', () async {
    final client = MockClient((request) async => http.Response(
          jsonEncode({'error': 'Папка не найдена'}),
          400,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ));
    final ws = SecondaryState();
    ws.bind(IltApi(
      ready: const ApiReady(port: 1111, token: 'tok'),
      client: client,
    ));
    final ok = await ws.registerExportFolder(r'D:\nope');
    expect(ok, isFalse);
    expect(ws.errorText, 'Папка не найдена');
    ws.clearError();
    expect(ws.errorText, isNull);
  });
}
