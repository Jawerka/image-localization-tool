import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/quick/quick_app.dart';
import 'package:ilt_desktop/src/quick/quick_image_view.dart';
import 'package:ilt_desktop/src/quick/quick_startup.dart';
import 'package:ilt_desktop/src/quick/window_bridge.dart';

void main() {
  testWidgets('оригинал доступен до API, затем включается обычная сессия', (
    tester,
  ) async {
    final directory = Directory.systemTemp.createTempSync('ilt-startup-');
    final file = File('${directory.path}/page.png')
      ..writeAsBytesSync(
        base64Decode(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC+gBAAGKAPuTunr/AAAAAElFTkSuQmCC',
        ),
      );
    var ready = false;
    QuickController? connected;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          hostWindows,
          (_) async => ready
              ? {'port': 1234, 'token': 'test'}
              : {
                  'paths': [file.path],
                },
        );
    await tester.pumpWidget(
      QuickStartup(
        loadPreview: (_) async => file.readAsBytesSync(),
        onReady: (controller) => connected = controller,
        onOpenEditor: (_) async {},
        controllerFactory: (apiReady) => QuickController(
          IltApi(
            ready: apiReady,
            client: MockClient((_) async => http.Response('{"items":[]}', 200)),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.runAsync(() async {
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pump();
    expect(find.byType(QuickImageView), findsOneWidget);
    expect(connected, isNull);
    expect(find.byType(AppBar), findsNothing);
    final transform = tester
        .widget<InteractiveViewer>(find.byType(InteractiveViewer))
        .transformationController!;
    final zoomed = Matrix4.identity()..scaleByDouble(2, 2, 2, 1);
    transform.value = zoomed;
    ready = true;
    await tester.pump(const Duration(milliseconds: 30));
    await tester.pump();
    expect(connected, isNotNull);
    expect(connected!.viewTransform.value, zoomed);
    expect(find.byType(QuickApp), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(hostWindows, null);
    directory.deleteSync(recursive: true);
  });

  testWidgets('ошибка запуска сохраняет окно без бесконечного ожидания', (
    tester,
  ) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          hostWindows,
          (_) async => {'error': 'Служебный процесс завершился'},
        );
    await tester.pumpWidget(
      QuickStartup(onReady: (_) {}, onOpenEditor: (_) async {}),
    );
    await tester.pump();
    expect(find.text('Служебный процесс завершился'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(hostWindows, null);
  });
}
