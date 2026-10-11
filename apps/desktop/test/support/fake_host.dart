import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';
import 'package:ilt_desktop/src/sidecar/sidecar_controller.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';

/// Подставной сайдкар: не запускает процесс, сразу отдаёт handshake.
class FakeSidecar extends SidecarController {
  FakeSidecar({this.failures = 0}) : super(attach: true);

  int failures;

  @override
  Future<ApiReady> start() async {
    if (failures > 0) {
      failures -= 1;
      throw SidecarStartException('нет питона');
    }
    return const ApiReady(port: 1111, token: 'tok');
  }

  @override
  void stop() {}
}

/// Подставной сервер хоста: bootstrap, jobs, SSE и типовые маршруты.
class FakeHost {
  FakeHost({
    Map<String, dynamic>? bootstrap,
    this.close409 = false,
    Map<String, dynamic> Function(String path, String method)? reply,
    this.glossary = const [],
  })  : bootstrap = bootstrap ?? <String, dynamic>{},
        reply = reply ?? ((path, method) => <String, dynamic>{});

  final Map<String, dynamic> bootstrap;
  final bool close409;
  final Map<String, dynamic> Function(String path, String method) reply;
  final List<Map<String, dynamic>> glossary;
  final List<String> requests = <String>[];
  final List<String> bodies = <String>[];
  final StreamController<List<int>> events = StreamController<List<int>>();

  http.Client get client => MockClient.streaming((request, bodyStream) async {
        final body = await bodyStream.bytesToString();
        requests.add('${request.method} ${request.url.path}');
        bodies.add(body);
        switch (request.url.path) {
          case '/api/bootstrap':
            return _json(bootstrap);
          case '/api/jobs':
            return _json({'paused': false, 'unfinished': false});
          case '/api/events':
            return http.StreamedResponse(
              events.stream,
              200,
              headers: {'content-type': 'text/event-stream'},
            );
          case '/api/project/close':
            if (close409 && !body.contains('"force":true')) {
              return _json(
                {'error': 'Есть несохранённые изменения', 'dirty': true},
                409,
              );
            }
            return _json({'project': null, 'pages': []});
          case '/api/project/glossary':
            if (request.method == 'GET') {
              return _json({'glossary': glossary});
            }
            final decoded = jsonDecode(body) as Map<String, dynamic>;
            return _json({'glossary': decoded['glossary'] ?? []});
          default:
            final custom = reply(request.url.path, request.method);
            return _json(custom);
        }
      });

  /// Дослать SSE-кадр в формате сервера (`event:` + конверт `{type, payload}`).
  void pushEvent(String type, Map<String, dynamic> payload) {
    events.add(utf8.encode(
      'event: $type\n'
      'data: ${jsonEncode({'type': type, 'payload': payload})}\n\n',
    ));
  }

  static http.StreamedResponse _json(
    Map<String, dynamic> data, [
    int status = 200,
  ]) =>
      http.StreamedResponse(
        Stream.value(utf8.encode(jsonEncode(data))),
        status,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
}

/// Поднять ShellState против [FakeHost].
Future<(ShellState, FakeHost)> readyHost({
  Map<String, dynamic>? bootstrap,
  bool close409 = false,
  Map<String, dynamic> Function(String path, String method)? reply,
  List<Map<String, dynamic>> glossary = const [],
}) async {
  final host = FakeHost(
    bootstrap: bootstrap,
    close409: close409,
    reply: reply,
    glossary: glossary,
  );
  final state = ShellState(
    sidecar: FakeSidecar(),
    apiFactory: (ready) => IltApi(ready: ready, client: host.client),
  );
  await state.start();
  return (state, host);
}

/// Окно побольше тестовых 800×600. В тестах глифы — квадраты em (Ahem),
/// поэтому хром шире реального; берём с запасом поверх минимальных 1100×700.
void sizeWindow(WidgetTester tester) {
  tester.view.physicalSize = const Size(2200, 1300);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Общая настройка «первый запуск пройден» для bootstrap.
Map<String, dynamic> settingsDone(Map<String, dynamic> extra) => {
      'source_lang': 'en',
      'target_lang': 'ru',
      'first_run_complete': true,
      ...extra,
    };
