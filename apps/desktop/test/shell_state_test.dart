import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/sidecar/sidecar_controller.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';

/// Подставной сайдкар: не запускает процесс, сразу отдаёт handshake.
class _FakeSidecar extends SidecarController {
  _FakeSidecar({this.failures = 0}) : super(attach: true);

  int failures;
  bool stopped = false;
  Completer<int> exitCompleter = Completer<int>();

  @override
  Future<int>? get processExitCode => exitCompleter.future;

  @override
  Future<ApiReady> start() async {
    if (failures > 0) {
      failures -= 1;
      throw SidecarStartException('нет питона');
    }
    exitCompleter = Completer<int>();
    return const ApiReady(port: 1111, token: 'tok');
  }

  @override
  void stop() {
    stopped = true;
  }
}

const _jsonUtf8 = {'content-type': 'application/json; charset=utf-8'};

MockClient _client({
  Map<String, dynamic>? bootstrap,
  int status = 200,
  bool events = true,
}) =>
    MockClient((request) async {
      if (request.url.path == '/api/bootstrap') {
        if (status != 200) {
          return http.Response('{"error": "Не авторизован"}', status,
              headers: _jsonUtf8);
        }
        return http.Response(jsonEncode(bootstrap ?? {}), 200,
            headers: _jsonUtf8);
      }
      if (request.url.path == '/api/events' && events) {
        return http.Response('', 200);
      }
      return http.Response('{}', 404, headers: _jsonUtf8);
    });

void main() {
  test('start читает bootstrap и переходит в ready', () async {
    final sidecar = _FakeSidecar();
    final state = ShellState(
      sidecar: sidecar,
      apiFactory: (ready) => IltApi(
        ready: ready,
        client: _client(
          bootstrap: {
            'settings': {'ui_scale': 125, 'theme': 'light'},
            'project': {'id': 'pr', 'name': 'Тест'},
          },
        ),
      ),
    );
    addTearDown(state.dispose);
    await state.start();
    expect(state.status, HostStatus.ready);
    expect(state.uiScale, 1.25);
    expect(state.themeName, 'light');
    expect(state.workspace.project?.name, 'Тест');
    expect(state.eventCount, 0);
  });

  test('401 от bootstrap → authError', () async {
    final state = ShellState(
      sidecar: _FakeSidecar(),
      apiFactory: (ready) => IltApi(ready: ready, client: _client(status: 401)),
    );
    addTearDown(state.dispose);
    await state.start();
    expect(state.status, HostStatus.error);
    expect(state.authError, isTrue);
    expect(state.errorMessage, contains('авторизации'));
  });

  test('ошибка старта сайдкара → error с сообщением', () async {
    final state = ShellState(
      sidecar: _FakeSidecar(failures: 1),
      apiFactory: (ready) => IltApi(ready: ready, client: _client()),
    );
    addTearDown(state.dispose);
    await state.start();
    expect(state.status, HostStatus.error);
    expect(state.authError, isFalse);
    expect(state.errorMessage, contains('нет питона'));
  });

  test('retry после ошибки доходит до ready', () async {
    final sidecar = _FakeSidecar(failures: 1);
    final state = ShellState(
      sidecar: sidecar,
      apiFactory: (ready) => IltApi(ready: ready, client: _client()),
    );
    addTearDown(state.dispose);
    await state.start();
    expect(state.status, HostStatus.error);
    await state.retry();
    expect(state.status, HostStatus.ready);
    expect(sidecar.stopped, isTrue);
  });

  test('смерть сайдкара в рантайме → error с Retry (US1#3)', () async {
    final sidecar = _FakeSidecar();
    final state = ShellState(
      sidecar: sidecar,
      apiFactory: (ready) => IltApi(ready: ready, client: _client()),
    );
    addTearDown(state.dispose);
    await state.start();
    expect(state.status, HostStatus.ready);
    sidecar.exitCompleter.complete(1);
    await Future<void>.delayed(Duration.zero);
    expect(state.status, HostStatus.error);
    expect(state.errorMessage, contains('код 1'));
  });

  test('retry после смерти процесса снова даёт ready', () async {
    final sidecar = _FakeSidecar();
    final state = ShellState(
      sidecar: sidecar,
      apiFactory: (ready) => IltApi(ready: ready, client: _client()),
    );
    addTearDown(state.dispose);
    await state.start();
    sidecar.exitCompleter.complete(1);
    await Future<void>.delayed(Duration.zero);
    expect(state.status, HostStatus.error);
    await state.retry();
    expect(state.status, HostStatus.ready);
    await Future<void>.delayed(Duration.zero);
    expect(state.status, HostStatus.ready);
  });
}
