import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/quick/quick_app.dart';
import 'package:ilt_desktop/src/quick/window_bridge.dart';
import 'package:ilt_desktop/src/sidecar/handshake.dart';

void main() {
  testWidgets('Копировать из ПКМ копирует перевод даже при показе оригинала', (
    tester,
  ) async {
    final calls = <String>[];
    MethodCall? copied;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(hostWindows, (call) async {
          copied = call;
          return null;
        });
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient((request) async {
        calls.add(request.url.path);
        return http.Response.bytes(
          base64Decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC+gBAAGKAPuTunr/AAAAAElFTkSuQmCC',
          ),
          200,
        );
      }),
    );
    final controller = QuickController(api)
      ..selected = 'translated'
      ..original = true
      ..items = [
        {'id': 'translated', 'status': 'done', 'has_result': true},
      ];
    await tester.pumpWidget(
      QuickApp(controller: controller, onOpenEditor: (_) async {}),
    );
    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(QuickSurface)),
      buttons: 2,
    );
    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.text('Копировать'), findsOneWidget);
    await tester.runAsync(() async {
      await controller.copyTranslation('translated');
      final call = copied!;
      expect(call.method, 'copyImage');
      expect(call.arguments['width'], 1);
      expect(call.arguments['height'], 1);
      expect(call.arguments['rgba'], hasLength(4));
    });
    expect(calls, ['/api/quick/image/translated/result']);
    await tester.pumpAndSettle();
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(hostWindows, null);
  });
  test(
    'неподставленный макрос FastStone показывает правильные параметры',
    () async {
      var imageRequests = 0;
      final api = IltApi(
        ready: const ApiReady(port: 1234, token: 'test'),
        client: MockClient((request) async {
          if (request.url.path.contains('/image/')) {
            imageRequests++;
            return http.Response('{}', 404);
          }
          return http.Response(
            jsonEncode({
              'selected_id': 'one',
              'items': [
                {
                  'id': 'one',
                  'name': '[filename]',
                  'source_path': 'D:/app/[filename]',
                  'status': 'error',
                  'error': 'Неподдерживаемый формат',
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      final controller = QuickController(api);
      await controller.refresh();
      expect(controller.error, contains('--quick (filename)'));
      expect(imageRequests, 0);
      controller.dispose();
    },
  );

  test('ошибка превью не скрывает причину отказа файла', () async {
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient((request) async {
        if (request.url.path.contains('/image/')) {
          return http.Response('{}', 404);
        }
        return http.Response(
          jsonEncode({
            'selected_id': 'one',
            'items': [
              {
                'id': 'one',
                'name': 'missing.png',
                'source_path': 'D:/missing.png',
                'status': 'error',
                'error': 'Файл исчез или не найден',
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    final controller = QuickController(api);
    await controller.refresh();
    expect(controller.error, 'Файл исчез или не найден');
    controller.dispose();
  });

  testWidgets('новый файл во время заметки не меняет кадр багрепорта', (
    tester,
  ) async {
    var selected = 'one';
    Map<String, dynamic>? report;
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient((request) async {
        if (request.url.path.endsWith('/bug-report')) {
          report = (jsonDecode(request.body) as Map).cast<String, dynamic>();
          return http.Response('{"path":""}', 200);
        }
        return http.Response(
          jsonEncode({
            'selected_id': selected,
            'busy': false,
            'items': [
              {
                'id': 'one',
                'status': 'error',
                'error': 'Ошибка 1',
                'has_result': false,
              },
              {
                'id': 'two',
                'status': 'error',
                'error': 'Ошибка 2',
                'has_result': false,
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    final controller = QuickController(api);
    await controller.refresh();
    await tester.pumpWidget(
      QuickApp(controller: controller, onOpenEditor: (_) async {}),
    );
    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(QuickSurface)),
      buttons: 2,
    );
    await gesture.up();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Багрепорт…'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Неверный перевод');
    selected = 'two';
    await controller.refresh();
    await tester.pump();
    await tester.tap(find.text('Сохранить отчёт'));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(seconds: 1));
    expect(report?['id'], 'one');
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets('пустое окно позволяет настроить сервер только из ПКМ', (
    tester,
  ) async {
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'selected_id': '',
            'busy': false,
            'items': [],
            'server': {'url': 'http://192.168.88.41:8765', 'paired': false},
          }),
          200,
        ),
      ),
    );
    final controller = QuickController(api);
    await controller.refresh();
    await tester.pumpWidget(
      QuickApp(controller: controller, onOpenEditor: (_) async {}),
    );
    expect(find.text('Сервер…'), findsNothing);
    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(QuickSurface)),
      buttons: 2,
    );
    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.text('Сервер…'), findsOneWidget);
    expect(find.text('Повторить'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  test(
    'готовый повтор обновляет пиксели, одинаковый опрос не перестраивает окно',
    () async {
      var status = 'running';
      var resultVersion = 1;
      var changes = 0;
      final api = IltApi(
        ready: const ApiReady(port: 1234, token: 'test'),
        client: MockClient((request) async {
          if (request.url.path.contains('/image/')) {
            return http.Response.bytes([resultVersion], 200);
          }
          return http.Response(
            jsonEncode({
              'selected_id': 'one',
              'busy': status != 'done',
              'items': [
                {
                  'id': 'one',
                  'source_path': 'page.png',
                  'job_id': 'retry',
                  'status': status,
                  'has_result': true,
                },
              ],
            }),
            200,
          );
        }),
      );
      final controller = QuickController(api)..addListener(() => changes++);
      await controller.refresh();
      await controller.refresh();
      expect(changes, 1);
      expect(controller.pixels, [1]);
      status = 'done';
      resultVersion = 2;
      await controller.refresh();
      expect(controller.pixels, [2]);
      controller.dispose();
    },
  );

  testWidgets('быстрое окно не содержит оболочку и действия доступны из ПКМ', (
    tester,
  ) async {
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'selected_id': 'one',
            'busy': false,
            'items': [
              {
                'id': 'one',
                'name': 'page.gif',
                'status': 'error',
                'error': 'Неподдерживаемый формат',
                'has_result': false,
                'progress': 0,
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    final controller = QuickController(api);
    await controller.refresh();
    await tester.pumpWidget(
      QuickApp(controller: controller, onOpenEditor: (_) async {}),
    );
    expect(find.text('Неподдерживаемый формат'), findsOneWidget);
    expect(find.byType(AppBar), findsNothing);
    expect(find.byType(IconButton), findsNothing);
    expect(find.text('Файл'), findsNothing);
    final point = tester.getCenter(find.byType(QuickSurface));
    final gesture = await tester.startGesture(point, buttons: 2);
    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.text('Багрепорт…'), findsOneWidget);
    expect(find.text('Повторить'), findsOneWidget);
    expect(find.text('Отменить'), findsNothing);
    expect(find.text('Копировать'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  test('выбранный queued кадр сохраняется при обновлении другого', () async {
    final api = IltApi(
      ready: const ApiReady(port: 1234, token: 'test'),
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'selected_id': 'two',
            'busy': true,
            'items': [
              {
                'id': 'one',
                'status': 'running',
                'progress': 65,
                'has_result': false,
              },
              {
                'id': 'two',
                'status': 'queued',
                'queue_position': 1,
                'progress': 0,
                'has_result': false,
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    final controller = QuickController(api);
    await controller.refresh();
    expect(controller.current?['id'], 'two');
    expect(controller.badge, 'В очереди 1');
    expect(controller.busy, isTrue);
    controller.dispose();
  });
}
