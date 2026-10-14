import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/app.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';

import 'support/fake_host.dart';

Map<String, dynamic> _runtimeReply() => {
      'platform': 'win',
      'python': '310',
      'packs': [
        {
          'id': 'torch-cpu',
          'title': 'PyTorch CPU (LaMa)',
          'kind': 'torch',
          'version': '2.11.0',
          'size_bytes': 178000000,
          'state': 'available',
          'recommended': false,
          'format': 'wheels',
          'source': 'PyPI + PyTorch CDN',
        },
        {
          'id': 'torch-cu128',
          'title': 'PyTorch CUDA 12.8 (NVIDIA)',
          'kind': 'torch',
          'version': '2.11.0+cu128',
          'size_bytes': 1400000000,
          'state': 'available',
          'recommended': true,
          'format': 'wheels',
          'source': 'PyPI + PyTorch CDN',
        },
        {
          'id': 'argos',
          'title': 'Argos Translate',
          'kind': 'argos',
          'version': '1.11.1',
          'size_bytes': 100000000,
          'state': 'available',
          'format': 'wheels',
          'source': 'PyPI + GitHub releases',
        },
      ],
      'hardware': {
        'vendor': 'nvidia',
        'name': 'RTX 5060',
        'driver': 617,
        'recommended': 'torch-cu128',
        'reason': 'CUDA доступна: драйвер 617 ≥ 570',
      },
      'torch_ready': false,
      'argos_ready': false,
      'device_effective': 'cpu',
      'download': {'id': '', 'state': 'idle'},
    };

Map<String, dynamic> _bootstrap() => {
      'settings': settingsDone({'first_run_complete': false}),
      'project': null,
      'pages': [],
      'version': '1.0.0',
      'paths': {'settings': r'D:\s.json', 'data': r'D:\data'},
      'has_api_key': false,
    };

void main() {
  testWidgets('мастер: шаг «Компоненты» и запуск скачивания', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _bootstrap(),
      reply: (path, method) => path == '/api/runtime' ? _runtimeReply() : {},
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();

    for (var index = 0; index < 4; index++) {
      await tester.tap(find.byKey(const Key('first-run-next')));
      await tester.pump();
    }
    await tester.tap(find.text('Дополнительные настройки компонентов'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(host.requests, contains('GET /api/runtime'));
    expect(find.text('PyTorch CUDA 12.8 (NVIDIA)'), findsOneWidget);
    expect(find.textContaining('рекомендовано'), findsOneWidget);
    expect(find.textContaining('CUDA доступна'), findsOneWidget);
    expect(find.textContaining('PyTorch CDN'), findsWidgets);
    expect(find.textContaining('~3 мин'), findsOneWidget);
    expect(find.textContaining('<1 мин'), findsWidgets);
    expect(find.textContaining('при следующей обработке'), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('wizard-runtime-download-torch-cu128')));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.byKey(const Key('wizard-runtime-download-torch-cu128')));
    await tester.pump();
    expect(host.requests, contains('POST /api/runtime/download'));
    expect(host.bodies.last, contains('torch-cu128'));
  });

  testWidgets('настройки: установленный компонент можно удалить', (tester) async {
    sizeWindow(tester);
    final bootstrap = _bootstrap();
    bootstrap['settings'] = settingsDone(const {});
    final (state, host) = await readyHost(
      bootstrap: bootstrap,
      reply: (path, method) {
        if (path != '/api/runtime') return {};
        final data = _runtimeReply();
        (data['packs'] as List)[2] = {
          'id': 'argos',
          'title': 'Argos Translate',
          'kind': 'argos',
          'version': '1.11.1',
          'size_bytes': 100000000,
          'installed_bytes': 120000000,
          'state': 'installed',
        };
        data['argos_ready'] = true;
        return data;
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    state.openOverlay(OverlayKind.settings);
    await tester.pump();
    await tester.tap(find.byKey(const Key('settings-nav-components')));
    await tester.pump();

    expect(find.byKey(const Key('component-remove-argos')), findsOneWidget);
    await tester.tap(find.byKey(const Key('component-remove-argos')));
    await tester.pump();
    await tester.pump();
    expect(host.requests, contains('POST /api/runtime/remove'));
    expect(host.bodies.last, contains('argos'));
  });

  testWidgets('мастер: ключ API сохраняется при проверке', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _bootstrap(),
      reply: (path, method) => path == '/api/runtime' ? _runtimeReply() : {},
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();

    for (var index = 0; index < 2; index++) {
      await tester.tap(find.byKey(const Key('first-run-next')));
      await tester.pump();
    }
    expect(find.text('Сервер LLM'), findsWidgets);
    expect(find.byKey(const Key('wizard-llm-api-key')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('wizard-llm-api-key')), 'sk-test');
    await tester.tap(find.byKey(const Key('wizard-llm-check')));
    await tester.pump();
    await tester.pump();

    final index = host.requests.indexOf('POST /api/settings/secret');
    expect(index, isNot(-1));
    expect(host.bodies[index], contains('sk-test'));
  });
}
