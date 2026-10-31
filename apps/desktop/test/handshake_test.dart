import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/sidecar/data_root.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';

void main() {
  test('tryParse принимает валидный handshake', () {
    final ready =
        ApiReady.tryParse('{"port": 4321, "token": "tok", "api_json": "x"}');
    expect(ready, isNotNull);
    expect(ready!.port, 4321);
    expect(ready.token, 'tok');
    expect(ready.baseUri.toString(), 'http://127.0.0.1:4321');
  });

  test('tryParse отвергает мусор', () {
    expect(ApiReady.tryParse(''), isNull);
    expect(ApiReady.tryParse('Запуск приложения'), isNull);
    expect(ApiReady.tryParse('{"port": 0, "token": "t"}'), isNull);
    expect(ApiReady.tryParse('{"port": 70000, "token": "t"}'), isNull);
    expect(ApiReady.tryParse('{"port": 80}'), isNull);
    expect(ApiReady.tryParse('{"port": 80, "token": ""}'), isNull);
    expect(ApiReady.tryParse('{"port": "80", "token": "t"}'), isNull);
  });

  test('кандидаты: env, repo/data, install/data — без LocalAppData', () {
    final dir = Directory.systemTemp.createTempSync('ilt-handshake');
    addTearDown(() => dir.deleteSync(recursive: true));
    final candidates = apiReadyCandidates(
      environment: {
        'ILT_API_JSON': '${dir.path}/explicit.json',
        'ILT_DATA_DIR': '${dir.path}/data',
        'LOCALAPPDATA': '${dir.path}/local',
      },
      executableDir: '${dir.path}/exe',
      repoRoot: '${dir.path}/repo',
    );
    expect(candidates.first, '${dir.path}/explicit.json');
    expect(candidates, contains('${dir.path}/data/api.json'));
    expect(candidates, contains('${dir.path}/repo/data/api.json'));
    expect(
      candidates,
      isNot(contains('${dir.path}/local/ImageLocalizationTool/api.json')),
    );
  });

  test('resolveDataRoot: installRoot/data без существующего каталога', () {
    final dir = Directory.systemTemp.createTempSync('ilt-root');
    addTearDown(() => dir.deleteSync(recursive: true));
    Directory('${dir.path}/desktop/data').createSync(recursive: true);
    final root = resolveDataRoot(
      environment: const {'LOCALAPPDATA': r'C:\local'},
      executableDir: '${dir.path}/desktop',
    );
    expect(root, '${dir.path}/data');
  });

  test('портативный data — в корне установки, ассеты desktop/data игнорируются', () {
    final dir = Directory.systemTemp.createTempSync('ilt-root');
    addTearDown(() => dir.deleteSync(recursive: true));
    Directory('${dir.path}/data').createSync();
    Directory('${dir.path}/desktop/data').createSync(recursive: true);
    final candidates = dataRootCandidates(
      environment: const {'LOCALAPPDATA': r'C:\local'},
      executableDir: '${dir.path}/desktop',
    );
    expect(candidates, contains('${dir.path}/data'));
    expect(candidates, isNot(contains('${dir.path}/desktop/data')));
    expect(
      candidates,
      isNot(contains(r'C:\local\ImageLocalizationTool')),
    );
  });

  test('readApiReadyFromFiles читает первый валидный', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-handshake-read');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = File('${dir.path}/api.json');
    file.writeAsStringSync('{"port": 1234, "token": "abc"}');
    final ready = await readApiReadyFromFiles(
      ['${dir.path}/missing.json', file.path],
    );
    expect(ready?.port, 1234);
    expect(ready?.token, 'abc');
  });

  test('removeStaleApiReady удаляет старые файлы', () {
    final dir = Directory.systemTemp.createTempSync('ilt-handshake-stale');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = File('${dir.path}/api.json');
    file.writeAsStringSync('{"port": 1, "token": "stale"}');
    removeStaleApiReady([file.path, '${dir.path}/нет.json']);
    expect(file.existsSync(), isFalse);
  });
}
