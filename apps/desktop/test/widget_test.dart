import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/api/ilt_api.dart';
import 'package:ilt_desktop/src/app.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';

import 'support/fake_host.dart';

Map<String, dynamic> _editorBootstrap() => {
      'settings': settingsDone({}),
      'project': {'id': 'pr', 'name': 'Ки́рби'},
      'pages': [
        {
          'id': 'a',
          'name': '001.jpg',
          'status': 'done',
          'progress': 100,
          'stage': 'typeset',
        },
        {
          'id': 'b',
          'name': '002.jpg',
          'status': 'running',
          'progress': 40,
          'stage': 'ocr',
        },
        {'id': 'c', 'name': '003.jpg', 'status': 'idle', 'progress': 0},
      ],
      'version': '2.0',
      'device': 'cpu',
      'llm': {
        'ok': true,
        'models': ['qwen2-vl'],
      },
    };

void main() {
  testWidgets('пустое окно: дропзона, недавние, disabled-действия', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: {
        'settings': settingsDone({}),
        'recent': [
          {'id': 'p1', 'name': 'Ки́рби', 'path': 'D:\\манга'},
        ],
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    expect(find.byKey(const Key('empty-dropzone')), findsOneWidget);
    expect(find.byKey(const Key('empty-open-files')), findsOneWidget);
    expect(find.byKey(const Key('empty-open-folder')), findsOneWidget);
    expect(find.byKey(const Key('pages-empty')), findsOneWidget);
    expect(find.byKey(const Key('shell-dock')), findsNothing);
    expect(find.byKey(const Key('top-project-chip')), findsOneWidget);
    expect(find.text('Проект не открыт'), findsWidgets);
    expect(find.byKey(const Key('recent-p1')), findsOneWidget);
    final translate = tester.widget<FilledButton>(
      find.byKey(const Key('top-translate')),
    );
    expect(translate.onPressed, isNull);
  });

  testWidgets('редактор: страницы, подвал, выбор включает перевод', (tester) async {
    sizeWindow(tester);
    final bootstrap = _editorBootstrap();
    bootstrap['pages'] = [
      {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
      {'id': 'c', 'name': '003.jpg', 'status': 'idle'},
    ];
    final (state, host) = await readyHost(bootstrap: bootstrap);
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    expect(find.byKey(const Key('page-row-a')), findsOneWidget);
    expect(find.byKey(const Key('page-row-c')), findsOneWidget);
    expect(find.text('1 из 2 готово'), findsOneWidget);
    // 027: превью страницы и высота поиска в рельсе (028: 32, кнопка убрана).
    expect(find.byKey(const Key('pages-thumb-a')), findsOneWidget);
    expect(
      tester.getSize(find.byKey(const Key('pages-search'))).height,
      32,
    );
    expect(find.byKey(const Key('pages-translate-all')), findsNothing);
    // Без активной страницы док скрыт (023: канвас вместо карточки).
    expect(find.byKey(const Key('viewer-dock')), findsNothing);
    expect(find.byKey(const Key('scene-no-selection')), findsOneWidget);
    expect(find.byKey(const Key('top-job-pill')), findsNothing);
    var translate = tester.widget<FilledButton>(
      find.byKey(const Key('top-translate')),
    );
    expect(translate.onPressed, isNull);
    await tester.tap(find.byKey(const Key('page-row-c')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer-dock')), findsOneWidget);
    translate = tester.widget<FilledButton>(
      find.byKey(const Key('top-translate')),
    );
    expect(translate.onPressed, isNotNull);
    // Живой SSE-конверт сервера `{type, payload}` доходит до строки.
    host.pushEvent('page.updated', {
      'job_id': 'j1',
      'project_id': 'pr',
      'page_id': 'c',
      'kind': 'translate_page',
      'status': 'running',
      'progress': 40,
      'stage': 'ocr',
    });
    await tester.pump();
    await tester.pump();
    // Статус виден в строке страницы; на сцене — пилюля этапа (023).
    expect(find.text('идёт 40 % · OCR'), findsOneWidget);
    expect(find.text('OCR · 40 %'), findsOneWidget);
  });

  testWidgets('batch: пилюля, пауза и стоп', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(bootstrap: _editorBootstrap());
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    expect(find.byKey(const Key('top-job-pill')), findsOneWidget);
    expect(find.byKey(const Key('pages-batch')), findsNothing);
    await tester.tap(find.byKey(const Key('pages-tab-queue')));
    await tester.pump();
    expect(find.byKey(const Key('pages-batch')), findsOneWidget);
    expect(find.byKey(const Key('batch-pause')), findsOneWidget);
    expect(find.byKey(const Key('batch-stop')), findsOneWidget);
    expect(find.byKey(const Key('scene-stage-pill')), findsOneWidget);
    expect(find.text('идёт 40 % · OCR'), findsOneWidget);
    await tester.tap(find.byKey(const Key('batch-pause')));
    await tester.pump();
    expect(host.requests, contains('POST /api/jobs/pause'));
  });

  testWidgets('очередь и хоткеи перевода: мгновенная реакция', (tester) async {
    sizeWindow(tester);
    final bootstrap = _editorBootstrap();
    bootstrap['pages'] = [
      {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
      {'id': 'c', 'name': '003.jpg', 'status': 'idle'},
    ];
    final (state, host) = await readyHost(bootstrap: bootstrap);
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    // Пункт «Перевести всё» живёт в меню кнопки «Перевести».
    await tester.tap(find.byKey(const Key('top-translate-menu')));
    await tester.pumpAndSettle();
    expect(find.text('Перевести всё'), findsOneWidget);
    await tester.tapAt(const Offset(4, 4));
    await tester.pumpAndSettle();
    // Ctrl+Shift+Enter — перевести всё: очередь видна сразу, POST уходит следом.
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(find.text('в очереди'), findsOneWidget);
    expect(host.requests, contains('POST /api/jobs/translate'));
    final translateAll =
        host.requests.lastIndexOf('POST /api/jobs/translate');
    expect(host.bodies[translateAll], contains('"skip_ready":true'));
    expect(find.byKey(const Key('top-job-pill')), findsOneWidget);
  });

  testWidgets('Ctrl+Enter переводит текущую страницу', (tester) async {
    sizeWindow(tester);
    final bootstrap = _editorBootstrap();
    bootstrap['pages'] = [
      {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
      {'id': 'c', 'name': '003.jpg', 'status': 'idle'},
    ];
    final (state, host) = await readyHost(bootstrap: bootstrap);
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    await tester.tap(find.byKey(const Key('page-row-c')));
    await tester.pumpAndSettle();
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pump();
    expect(host.requests, contains('POST /api/jobs/translate'));
    final translateOne =
        host.requests.lastIndexOf('POST /api/jobs/translate');
    expect(host.bodies[translateOne], contains('"scope":"page"'));
    expect(host.bodies[translateOne], contains('"page_id":"c"'));
    expect(find.text('в очереди'), findsOneWidget);
  });

  testWidgets('ошибка старта: сообщение и повтор', (tester) async {
    sizeWindow(tester);
    final host = FakeHost();
    final state = ShellState(
      sidecar: FakeSidecar(failures: 1),
      apiFactory: (ready) => IltApi(ready: ready, client: host.client),
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await state.start();
    await tester.pumpWidget(IltApp(state: state));
    expect(find.text('нет питона'), findsOneWidget);
    await tester.tap(find.byKey(const Key('shell-retry')));
    await tester.pump();
    expect(find.byKey(const Key('empty-dropzone')), findsOneWidget);
  });

  testWidgets('грязное закрытие: полоса и force', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: _editorBootstrap(),
      close409: true,
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await state.workspace.closeProject();
    await tester.pump();
    expect(find.byKey(const Key('shell-dirty-strip')), findsOneWidget);
    await tester.tap(find.byKey(const Key('dirty-close-force')));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('shell-dirty-strip')), findsNothing);
    expect(find.byKey(const Key('empty-dropzone')), findsOneWidget);
    expect(host.requests.where((r) => r == 'POST /api/project/close').length, 2);
  });
}
