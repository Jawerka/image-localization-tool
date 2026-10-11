import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/app.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';
import 'package:ilt_desktop/src/ui/theme.dart';

import 'support/fake_host.dart';

Map<String, dynamic> _bootstrap({Map<String, dynamic>? settings}) => {
      'settings': settingsDone(settings ?? {}),
      'project': {'id': 'pr', 'name': 'Сериал'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        {'id': 'b', 'name': '002.jpg', 'status': 'idle'},
      ],
      'version': '1.2.3',
      'paths': {'settings': r'D:\s.json', 'data': r'D:\data'},
      'has_api_key': false,
    };

void main() {
  testWidgets('настройки: правка темы применяется и уходит одним PUT',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _bootstrap(settings: {'theme': 'dark'}),
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    state.openOverlay(OverlayKind.settings);
    await tester.pump();
    expect(find.byKey(const Key('settings-screen')), findsOneWidget);
    expect(find.text('Сбросить к значениям по умолчанию'), findsOneWidget);

    await tester.tap(find.text('Светлая').first);
    await tester.pump();
    expect(state.themeName, 'light');

    await tester.tap(find.byKey(const Key('settings-ok')));
    await tester.pump();
    await tester.pump();
    expect(state.overlay, isNull);
    expect(host.requests, contains('PUT /api/settings'));
    expect(host.bodies.last, contains('"theme":"light"'));
  });

  testWidgets('настройки: отмена возвращает тему и подсказку Esc',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _bootstrap(settings: {'theme': 'dark'}),
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    state.openOverlay(OverlayKind.settings);
    await tester.pump();
    await tester.tap(find.text('Светлая').first);
    await tester.pump();
    expect(state.themeName, 'light');
    await tester.tap(find.byKey(const Key('settings-cancel')));
    await tester.pump();
    expect(state.overlay, isNull);
    expect(state.themeName, 'dark');
    expect(host.requests.where((r) => r.startsWith('PUT')).toList(), isEmpty);

    // Esc закрывает оверлей.
    state.openOverlay(OverlayKind.settings);
    await tester.pump();
    expect(find.byKey(const Key('settings-screen')), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pump();
    expect(state.overlay, isNull);
  });

  testWidgets('глоссарий: загрузка, правка и сохранение', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _bootstrap(),
      glossary: [
        {'source': 'Alice', 'target': 'Алиса', 'gender': 'f', 'note': ''},
      ],
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    state.openOverlay(OverlayKind.glossary);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(const Key('glossary-screen')), findsOneWidget);
    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('Алиса'), findsOneWidget);

    await tester.tap(find.byKey(const Key('glossary-edit-0')));
    await tester.pump();
    final fields = find.descendant(
      of: find.byKey(const Key('glossary-row-0')),
      matching: find.byType(TextField),
    );
    expect(fields, findsNWidgets(3));
    await tester.enterText(fields.at(1), 'Алиса П.');
    await tester.tap(find.byKey(const Key('glossary-commit')));
    await tester.pump();
    expect(find.text('Алиса П.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('glossary-save')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(host.requests, contains('PUT /api/project/glossary'));
    expect(host.bodies.last, contains('Алиса П.'));
  });

  testWidgets('первый запуск: мастер показывается и пропускается', (tester) async {
    sizeWindow(tester);
    final bootstrap = _bootstrap();
    (bootstrap['settings'] as Map)['first_run_complete'] = false;
    final (state, host) = await readyHost(bootstrap: bootstrap);
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    expect(find.byKey(const Key('first-run-screen')), findsOneWidget);
    expect(find.text('Добро пожаловать'), findsOneWidget);

    await tester.tap(find.byKey(const Key('first-run-skip')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('first-run-screen')), findsNothing);
    expect(host.requests, contains('PUT /api/settings'));
    expect(host.bodies.last, contains('first_run_complete'));
  });

  testWidgets('F1 открывает горячие клавиши, поиск фильтрует', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(bootstrap: _bootstrap());
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.f1);
    await tester.pump();
    expect(find.byKey(const Key('hotkeys-dialog')), findsOneWidget);
    expect(find.text('Вписать'), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('hotkeys-search')),
      'экспорт',
    );
    await tester.pump();
    final inDialog = find.descendant(
      of: find.byKey(const Key('hotkeys-dialog')),
      matching: find.text('Экспорт'),
    );
    expect(inDialog, findsOneWidget);
    expect(find.text('Вписать'), findsNothing);
  });

  testWidgets('выход при прогоне: диалог и «Выйти сейчас»', (tester) async {
    sizeWindow(tester);
    final bootstrap = _bootstrap();
    bootstrap['pages'] = [
      {'id': 'b', 'name': '002.jpg', 'status': 'running', 'progress': 20},
    ];
    final (state, host) = await readyHost(bootstrap: bootstrap);
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    expect(state.workspace.busy, isTrue);
    final future = state.confirmExit();
    await tester.pump();
    expect(find.byKey(const Key('exit-dialog')), findsOneWidget);
    await tester.tap(find.byKey(const Key('exit-now')));
    await tester.pump();
    expect(await future, ui.AppExitResponse.exit);
  });

  testWidgets('worker.failed открывает диалог, «Повторить ошибки» шлёт запрос',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(bootstrap: _bootstrap());
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    host.pushEvent('worker.failed', {'error': 'не найдена модель LaMa'});
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('worker-dialog')), findsOneWidget);
    expect(find.text('не найдена модель LaMa'), findsOneWidget);
    await tester.tap(find.byKey(const Key('worker-retry')));
    await tester.pump();
    await tester.pump();
    expect(host.requests, contains('POST /api/jobs/retry-errors'));
    expect(find.byKey(const Key('worker-dialog')), findsNothing);
  });

  testWidgets('экспорт: диалог со счётчиками и сводкой', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(bootstrap: _bootstrap());
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    await tester.tap(find.byKey(const Key('top-export')));
    await tester.pump();
    expect(find.byKey(const Key('export-dialog')), findsOneWidget);
    expect(find.text('Только готовые'), findsOneWidget);
    expect(find.text('1 страница'), findsOneWidget);
    expect(find.textContaining('добавление номера'), findsOneWidget);
    final run = tester.widget<FilledButton>(find.byKey(const Key('export-run')));
    expect(run.onPressed, isNotNull);
    expect(find.text('Экспорт 1 страница'), findsOneWidget);
  });

  testWidgets('тема: оверлей настроек и диалог правок следуют настройке',
      (tester) async {
    sizeWindow(tester);
    for (final (themeName, expected) in [
      ('dark', Brightness.dark),
      ('light', Brightness.light),
    ]) {
      final (state, host) = await readyHost(
        bootstrap: _bootstrap(settings: {'theme': themeName}),
        reply: (path, method) => path.startsWith('/api/pages/')
            ? <String, dynamic>{
                'page': {'id': path.split('/').last},
                'document': {
                  'version': 1,
                  'regions': <dynamic>[],
                  'strokes': <dynamic>[],
                },
              }
            : <String, dynamic>{},
      );
      await tester.pumpWidget(IltApp(state: state));
      await tester.tap(find.byKey(const Key('page-row-a')));
      await tester.pumpAndSettle();

      // Оверлей настроек живёт вне Theme оболочки — тему даёт MaterialApp.
      state.openOverlay(OverlayKind.settings);
      await tester.pump();
      final overlayContext =
          tester.element(find.byKey(const Key('settings-screen')));
      expect(Theme.of(overlayContext).brightness, expected, reason: themeName);
      expect(
        identical(
          IltPalette.of(overlayContext),
          expected == Brightness.dark ? IltPalette.dark : IltPalette.light,
        ),
        isTrue,
        reason: themeName,
      );
      state.closeOverlay();
      await tester.pump();

      // Диалог «Неприменённые правки» — тот же MaterialApp-контекст.
      final viewer = state.workspace.viewer;
      viewer.editDocument(
        (document) => document.addStroke(
          const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
        ),
        deferApply: true,
      );
      await tester.pump();
      await viewer.guardOrRun(() async {});
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('viewer-leave-dialog')), findsOneWidget);
      final dialogContext =
          tester.element(find.byKey(const Key('viewer-leave-dialog')));
      expect(Theme.of(dialogContext).brightness, expected, reason: themeName);
      expect(
        identical(
          IltPalette.of(dialogContext),
          expected == Brightness.dark ? IltPalette.dark : IltPalette.light,
        ),
        isTrue,
        reason: themeName,
      );
      await tester.tap(find.byKey(const Key('viewer-leave-stay')));
      await tester.pumpAndSettle();

      // Размонтируем дерево: ShellRoot подписывается на состояние в initState,
      // без этого второй прогон слушал бы прежний ShellState.
      await tester.pumpWidget(const SizedBox.shrink());
      state.dispose();
      host.events.close();
    }
  });
}
