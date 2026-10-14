import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/ui/preparation_panel.dart';

import 'support/fake_host.dart';

void main() {
  testWidgets('подготовка: одна кнопка, объём и выбор CPU без ключа API', (tester) async {
    Map<String, dynamic> current = {};
    final (state, host) = await readyHost(reply: (path, method) {
      if (path == '/api/preparation') return current;
      if (path == '/api/preparation/plan') {
        return {'state': 'idle', 'total': 300000000, 'required_space': 600000000};
      }
      if (path == '/api/preparation/start') {
        current = {'state': 'downloading', 'total': 300000000, 'done': 0, 'current': 'Распознавание'};
        return current;
      }
      return {};
    });
    addTearDown(() { state.dispose(); host.events.close(); });
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: PreparationPanel(
      state: state.secondary,
      selection: const {'translator_backend': 'argos', 'source_lang': 'en', 'target_lang': 'ru', 'api_key': 'secret'},
    ))));
    await tester.pump();
    await tester.pump();
    expect(find.text('Нужно скачать: 300.0 МБ'), findsOneWidget);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    await tester.tap(find.byKey(const Key('preparation-start')));
    await tester.pump();
    expect(host.requests, contains('POST /api/preparation/start'));
    expect(host.bodies.join(), contains('"device":"cpu"'));
    expect(host.bodies.join(), isNot(contains('secret')));
    expect(find.byKey(const Key('preparation-pause')), findsOneWidget);
  });

  testWidgets('подготовка: восстановленный снимок предлагает продолжение', (tester) async {
    final (state, host) = await readyHost(reply: (path, method) {
      if (path == '/api/preparation') {
        return {'state': 'paused', 'total': 1000000, 'done': 500000, 'current': 'Оффлайн-перевод'};
      }
      if (path == '/api/preparation/plan') return {'state': 'idle', 'total': 1000000};
      if (path == '/api/preparation/resume') return {'state': 'downloading', 'total': 1000000, 'done': 500000};
      return {};
    });
    addTearDown(() { state.dispose(); host.events.close(); });
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: PreparationPanel(
      state: state.secondary, selection: const {},
    ))));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('preparation-resume')), findsOneWidget);
    await tester.tap(find.byKey(const Key('preparation-resume')));
    await tester.pump();
    expect(host.requests, contains('POST /api/preparation/resume'));
    state.secondary.applyPreparationProgress({'state': 'ready', 'total': 1000000, 'done': 1000000});
    await tester.pump();
    expect(find.text('Нужные компоненты уже установлены.'), findsOneWidget);
  });
}
