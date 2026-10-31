import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/state/workspace_state.dart';

/// Записанный запрос: метод, путь, тело.
class _Sent {
  _Sent(this.method, this.path, this.body);

  final String method;
  final String path;
  final String body;
}

WorkspaceState _workspace(
  Map<String, dynamic> Function(String path)? reply,
  List<_Sent> sent, {
  int status = 200,
  bool failFirstSettings = false,
}) {
  var settingsCalls = 0;
  final client = MockClient((request) async {
    sent.add(_Sent(request.method, request.url.path, request.body));
    final data = reply?.call(request.url.path) ?? <String, dynamic>{};
    var code = status;
    if (failFirstSettings &&
        request.method == 'PUT' &&
        request.url.path == '/api/settings') {
      if (settingsCalls == 0) code = 500;
      settingsCalls += 1;
    }
    return http.Response(
      jsonEncode(data),
      code,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  });
  final ws = WorkspaceState();
  ws.bind(
    IltApi(
      ready: const ApiReady(port: 1111, token: 'tok'),
      client: client,
    ),
  );
  return ws;
}

void main() {
  test('bootstrap заполняет проект, страницы и недавние', () {
    final ws = _workspace(null, []);
    ws.applyBootstrap({
      'project': {'id': 'pr', 'name': 'Ки́рби'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        {'id': 'b', 'name': '002.jpg', 'status': 'idle'},
      ],
      'recent': [
        {'id': 'pr', 'name': 'Ки́рби', 'path': 'D:\\манга'},
      ],
      'version': '2.0.0',
    });
    expect(ws.hasProject, isTrue);
    expect(ws.project?.name, 'Ки́рби');
    expect(ws.pages.length, 2);
    expect(ws.recent.single.name, 'Ки́рби');
    expect(ws.batch.total, 2);
    expect(ws.batch.finished, 1);
    expect(ws.batch.percent, 50);
  });

  test('событие page.updated двигает строку и счётчики', () {
    final ws = _workspace(null, []);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'queued'},
      ],
    });
    expect(ws.busy, isTrue);
    ws.applyEvent('page.updated', {
      'page_id': 'a',
      'status': 'running',
      'progress': 40,
      'stage': 'ocr',
    });
    expect(ws.pages.single.isRunning, isTrue);
    expect(ws.pages.single.progress, 40);
    expect(ws.pages.single.stage, 'ocr');
    ws.applyEvent('page.updated', {
      'page_id': 'a',
      'status': 'done',
      'progress': 100,
      'stage': 'typeset',
    });
    expect(ws.busy, isFalse);
    expect(ws.batch.finished, 1);
  });

  test('worker.failed показывает сообщение, clearError убирает', () {
    final ws = _workspace(null, []);
    ws.applyEvent('worker.failed', {'error': 'LLM не ответил'});
    expect(ws.errorText, contains('LLM'));
    ws.clearError();
    expect(ws.errorText, isNull);
  });

  test('выбор, поиск и фильтр проблем', () {
    final ws = _workspace(null, []);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
        {'id': 'b', 'name': '002.jpg', 'status': 'error', 'error': 'сбой'},
        {'id': 'c', 'name': '003.jpg', 'status': 'done'},
      ],
    });
    ws.selectPage('a');
    expect(ws.activeId, 'a');
    ws.selectPage('b', toggle: true);
    expect(ws.selectedIds, containsAll(['a', 'b']));
    ws.setQuery('002');
    expect(ws.visiblePages.single.id, 'b');
    ws.setQuery('');
    ws.setProblemsOnly(true);
    expect(ws.visiblePages.single.id, 'b');
  });

  test('translate all: запрос scope=all и очередь локально', () async {
    final sent = <_Sent>[];
    final ws = _workspace((path) {
      if (path == '/api/jobs/translate') return {'job_id': 'j1'};
      return {};
    }, sent);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
        {'id': 'b', 'name': '002.jpg', 'status': 'done'},
      ],
    });
    await ws.translate();
    expect(sent.last.method, 'POST');
    expect(sent.last.path, '/api/jobs/translate');
    expect(sent.last.body, contains('"scope":"all"'));
    expect(sent.last.body, contains('"skip_ready":true'));
    expect(ws.pages.first.status, 'queued');
    expect(ws.pages.last.status, 'done');
    expect(ws.busy, isTrue);
  });

  test('translate: очередь видна до ответа сервера', () async {
    final sent = <_Sent>[];
    final ws = _workspace((path) => {'job_id': 'j1'}, sent);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
      ],
    });
    final future = ws.translate();
    expect(ws.pages.single.status, 'queued');
    expect(ws.busy, isTrue);
    await future;
    final translate = sent.lastWhere((r) => r.path == '/api/jobs/translate');
    expect(translate.method, 'POST');
  });

  test('translate: ошибка POST откатывает очередь', () async {
    final sent = <_Sent>[];
    final client = MockClient((request) async {
      sent.add(_Sent(request.method, request.url.path, request.body));
      return http.Response(
        jsonEncode({'error': 'LLM недоступен'}),
        500,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    final ws = WorkspaceState();
    ws.bind(IltApi(
      ready: const ApiReady(port: 1111, token: 'tok'),
      client: client,
    ));
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
      ],
    });
    await ws.translate(pageId: 'a');
    expect(ws.pages.single.status, 'idle');
    expect(ws.busy, isFalse);
    expect(ws.errorText, isNotNull);
  });

  test('job.progress: строка «running» со стадией воркера', () {
    final ws = _workspace(null, []);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'edited'},
      ],
    });
    ws.applyEvent('job.progress', {
      'page_id': 'a',
      'status': 'Маска букв',
      'progress': 65,
      'stage': 'mask',
    });
    expect(ws.pages.single.status, 'running');
    expect(ws.pages.single.progress, 65);
    expect(ws.pages.single.stage, 'mask');
    expect(ws.pages.single.error, isEmpty);
    expect(ws.busy, isTrue);
    // Без page_id событие никого не трогает.
    ws.applyEvent('job.progress', {'status': 'Вёрстка', 'progress': 90});
    expect(ws.pages.single.progress, 65);
  });

  test('слои: все комбинации из bootstrap и старые настройки', () {
    for (final boxes in [false, true]) {
      for (final mask in [false, true]) {
        final ws = _workspace(null, []);
        ws.applyBootstrap({
          'settings': {
            'viewer_show_boxes': boxes,
            'viewer_show_mask': mask,
          },
        });
        expect(ws.viewer.showBoxes, boxes);
        expect(ws.viewer.showMask, mask);
        ws.dispose();
      }
    }
    final ws = _workspace(null, []);
    ws.applyBootstrap({'settings': <String, dynamic>{}});
    expect(ws.viewer.showBoxes, isTrue);
    expect(ws.viewer.showMask, isTrue);
    ws.dispose();
  });

  test('слои: последнее быстрое переключение сохраняется', () async {
    final sent = <_Sent>[];
    final ws = _workspace(null, sent);
    ws.applyBootstrap({'settings': <String, dynamic>{}});
    ws.viewer
      ..setShowBoxes(false)
      ..setShowBoxes(true)
      ..setShowMask(false);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final body = jsonDecode(sent.last.body) as Map<String, dynamic>;
    expect(body['viewer_show_boxes'], isTrue);
    expect(body['viewer_show_mask'], isFalse);
    expect(sent.last.path, '/api/settings');
    ws.dispose();
  });

  test('слои: после ошибки первого запроса уходит более новый патч', () async {
    final sent = <_Sent>[];
    final ws = _workspace(null, sent, failFirstSettings: true);
    ws.applyBootstrap({'settings': <String, dynamic>{}});
    ws.viewer.setShowBoxes(false);
    ws.viewer.setShowBoxes(true);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    final puts = sent
        .where((item) => item.path == '/api/settings')
        .toList();
    expect(puts.length, 2);
    final body = jsonDecode(puts.last.body) as Map<String, dynamic>;
    expect(body['viewer_show_boxes'], isTrue);
    expect(ws.viewer.showBoxes, isTrue);
    ws.dispose();
  });

  test('слои: ошибка записи видна, видимость не откатывается', () async {
    final sent = <_Sent>[];
    final ws = _workspace(null, sent, status: 500);
    ws.applyBootstrap({'settings': <String, dynamic>{}});
    ws.viewer.setShowBoxes(false);
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(ws.viewer.showBoxes, isFalse);
    expect(ws.errorText, isNotNull);
    ws.dispose();
  });

  test('setDockPosition: локально сразу и PUT настроек', () async {
    final sent = <_Sent>[];
    final ws = _workspace(null, sent);
    ws.applyBootstrap({'settings': {'dock_position': 'bottom'}});
    expect(ws.dockAtTop, isFalse);
    await ws.setDockPosition(true);
    expect(ws.dockAtTop, isTrue);
    expect(sent.single.method, 'PUT');
    expect(sent.single.path, '/api/settings');
    expect(sent.single.body, contains('"dock_position":"top"'));
    await ws.setDockPosition(false);
    expect(ws.dockAtTop, isFalse);
    expect(sent.last.body, contains('"dock_position":"bottom"'));
  });

  test('clearRecent шлёт PUT настроек', () async {
    final sent = <_Sent>[];
    final ws = _workspace(null, sent);
    ws.applyBootstrap({
      'recent': [
        {'id': 'p1'},
      ],
    });
    await ws.clearRecent();
    expect(sent.single.method, 'PUT');
    expect(sent.single.path, '/api/settings');
    expect(sent.single.body, contains('recent_projects'));
    expect(ws.recent, isEmpty);
  });

  test('импорт перечитывает bootstrap, ошибка видна в errorText', () async {
    final sent = <_Sent>[];
    final ws = _workspace((path) {
      if (path == '/api/import') return {'project': null, 'pages': []};
      if (path == '/api/bootstrap') {
        return {
          'project': {'id': 'pr', 'name': 'Новый'},
          'pages': [
            {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
          ],
          'recent': [
            {'id': 'pr', 'name': 'Новый'},
          ],
        };
      }
      return {};
    }, sent);
    await ws.importPaths(['D:\\манга']);
    expect(sent.first.path, '/api/import');
    expect(sent.first.body, contains('D:\\\\манга'));
    expect(sent.last.path, '/api/bootstrap');
    expect(ws.project?.name, 'Новый');
    expect(ws.pages.length, 1);
  });

  test('закрытие с 409 → dirtyClose, force закрывает', () async {
    final sent = <_Sent>[];
    final client = MockClient((request) async {
      sent.add(_Sent(request.method, request.url.path, request.body));
      if (request.url.path == '/api/project/close' &&
          !request.body.contains('"force":true')) {
        return http.Response(
          jsonEncode({'error': 'Есть несохранённые изменения'}),
          409,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response(
        jsonEncode({'project': null, 'pages': []}),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    final ws = WorkspaceState();
    ws.bind(IltApi(
      ready: const ApiReady(port: 1111, token: 'tok'),
      client: client,
    ));
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'idle'},
      ],
    });
    await ws.closeProject();
    expect(ws.dirtyClose, isTrue);
    expect(ws.hasProject, isTrue);
    expect(ws.errorText, contains('несохранённые'));
    await ws.closeProject(force: true);
    expect(ws.dirtyClose, isFalse);
    expect(ws.hasProject, isFalse);
    expect(sent.last.body, contains('"force":true'));
  });

  test('отмена прогона возвращает строки в idle', () async {
    final sent = <_Sent>[];
    final ws = _workspace((path) {
      if (path == '/api/jobs/cancel') {
        return {'ok': true, 'paused': false, 'unfinished': false};
      }
      return {};
    }, sent);
    ws.applyBootstrap({
      'project': {'id': 'pr'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'running', 'progress': 40},
        {'id': 'b', 'name': '002.jpg', 'status': 'queued'},
        {'id': 'c', 'name': '003.jpg', 'status': 'done', 'progress': 100},
      ],
    });
    await ws.cancelJobs();
    expect(ws.pages[0].status, 'idle');
    expect(ws.pages[1].status, 'idle');
    expect(ws.pages[2].status, 'done');
    expect(ws.busy, isFalse);
  });
}
