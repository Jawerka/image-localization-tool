import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/errors.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';

void main() {
  const ready = ApiReady(port: 1234, token: 'tok');

  test('cookie и путь запроса', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('{"ok": true}', 200);
    });
    final api = IltApi(ready: ready, client: client);
    final payload = await api.getJson('/api/bootstrap');
    expect(payload['ok'], true);
    expect(captured.headers['Cookie'], 'ilt_session=tok');
    expect(captured.url.toString(), 'http://127.0.0.1:1234/api/bootstrap');
  });

  test('postJson отправляет JSON-тело', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('{}', 200);
    });
    final api = IltApi(ready: ready, client: client);
    await api.postJson('/api/drop', {
      'paths': ['C:\\page.png'],
    });
    expect(captured.method, 'POST');
    expect(captured.headers['Content-Type'], contains('application/json'));
    expect(captured.body, contains('page.png'));
  });

  test('401 → ApiAuthException', () async {
    final api = IltApi(
      ready: ready,
      client: MockClient(
        (_) async => http.Response(
          '{"error": "нет"}',
          401,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    await expectLater(
      api.getJson('/api/bootstrap'),
      throwsA(isA<ApiAuthException>()),
    );
  });

  test('500 → ApiException', () async {
    final api = IltApi(
      ready: ready,
      client: MockClient(
        (_) async => http.Response(
          '{"error": "бум"}',
          500,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    await expectLater(
      api.getJson('/api/bootstrap'),
      throwsA(isA<ApiException>()),
    );
  });

  test('openEvents проверяет статус', () async {
    final api = IltApi(
      ready: ready,
      client: MockClient(
        (_) async => http.Response(
          '{"error": "нет"}',
          401,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    await expectLater(api.openEvents(), throwsA(isA<ApiAuthException>()));

    final ok = IltApi(
      ready: ready,
      client: MockClient((request) async {
        expect(request.headers['Cookie'], 'ilt_session=tok');
        return http.Response('', 200);
      }),
    );
    final response = await ok.openEvents();
    expect(response.statusCode, 200);
  });
}
