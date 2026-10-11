import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/app.dart';

import 'support/fake_host.dart';

Map<String, dynamic> _doc() => <String, dynamic>{
      'version': 3,
      'regions': [
        {
          'id': '1',
          'bbox': [10, 10, 100, 100],
          'text': 'HI',
          'translation': '',
        },
        {
          'id': '2',
          'bbox': [200, 200, 80, 60],
          'text': 'GRRRRR',
          'translation': 'РРРРР',
          'type': 'sfx',
          'block_type': 'sfx',
          'overflow': true,
        },
      ],
      'strokes': <dynamic>[],
      'ocr_engine': 'rapidocr',
      'translator_engine': 'argos',
      'timings': {'detect': 1.24},
    };

void main() {
  testWidgets('инспектор: карточки, выделение и автосохранение текста',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: {
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        ],
      },
      reply: (path, method) {
        if (path == '/api/pages/a') {
          return <String, dynamic>{
            'page': {'id': 'a'},
            'document': _doc(),
          };
        }
        return <String, dynamic>{};
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();

    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();

    // Две карточки, у второй — флаг «Не влез», свёрнутые без полей.
    expect(find.byKey(const Key('region-card-1')), findsOneWidget);
    expect(find.byKey(const Key('region-card-2')), findsOneWidget);
    expect(find.byKey(const Key('region-translation-1')), findsNothing);
    expect(find.text('Не влез'), findsOneWidget);

    // Выделение карточки синхронизировано с канвасом.
    await tester.tap(find.byKey(const Key('region-card-head-2')));
    await tester.pumpAndSettle();
    expect(state.workspace.viewer.selectedRegionId, '2');
    expect(find.byKey(const Key('region-translation-2')), findsOneWidget);
    expect(find.text('2 / 2'), findsOneWidget);

    // Автосохранение перевода: одна правка и чип «Автосохранено».
    await tester.enterText(
      find.byKey(const Key('region-translation-2')),
      'РРРРР!',
    );
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump();
    expect(
      host.requests.where((r) => r == 'PUT /api/pages/a/document'),
      hasLength(1),
    );
    final putIndex = host.requests.indexOf('PUT /api/pages/a/document');
    final body = jsonDecode(host.bodies[putIndex]) as Map<String, dynamic>;
    final region = ((body['document'] as Map)['regions'] as List)
        .cast<Map<String, dynamic>>()
        .firstWhere((item) => '${item['id']}' == '2');
    expect(region['translation'], 'РРРРР!');
    expect(region['translation_locked'], true);
    expect(find.text('Автосохранено'), findsOneWidget);
  });

  testWidgets('инспектор: стиль и действия идут в черновик',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: {
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        ],
      },
      reply: (path, method) {
        if (path == '/api/pages/a') {
          return <String, dynamic>{
            'page': {'id': 'a'},
            'document': _doc(),
          };
        }
        return <String, dynamic>{};
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('region-card-head-1')));
    await tester.pumpAndSettle();

    // «Не переводить» без черновика сохраняется сразу.
    await tester.tap(find.byKey(const Key('region-skip-1')));
    await tester.pump(const Duration(milliseconds: 30));
    await tester.pump();
    expect(
      host.requests
          .where((r) => r == 'PUT /api/pages/a/document')
          .toList(),
      hasLength(1),
    );
    final skipIndex = host.requests.indexOf('PUT /api/pages/a/document');
    final skipBody = jsonDecode(host.bodies[skipIndex]) as Map<String, dynamic>;
    final skipRegion = ((skipBody['document'] as Map)['regions'] as List).first
        as Map<String, dynamic>;
    expect(skipRegion['skip'], true);

    // Пресет искривления — в черновик, пилюля «N правок».
    await tester.tap(find.byKey(const Key('style-warp-wave')));
    await tester.pump();
    expect(state.workspace.viewer.hasDeferredDraft, isTrue);
    expect(state.workspace.viewer.editCount, 1);
    expect(find.byKey(const Key('viewer-done-pill')), findsOneWidget);
    final style = state.workspace.viewer.document!.findRegion('1')!.styleMap();
    expect(style['warp']['kind'], 'wave');

    // Удаление — в черновик, выделение снимается.
    await tester.tap(find.byKey(const Key('region-delete-1')));
    await tester.pump();
    expect(state.workspace.viewer.document!.regions, hasLength(1));
    expect(state.workspace.viewer.selectedRegionId, isNull);
    expect(find.byKey(const Key('region-card-1')), findsNothing);
  });

  testWidgets('инспектор: вкладка «Страница» и отчёт при прогоне',
      (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: {
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
          {
            'id': 'b',
            'name': '002.jpg',
            'status': 'running',
            'progress': 40,
            'stage': 'ocr',
          },
          {
            'id': 'c',
            'name': '003.jpg',
            'status': 'error',
            'error': 'LLM не ответил',
          },
        ],
      },
      reply: (path, method) {
        if (path == '/api/pages/a') {
          return <String, dynamic>{
            'page': {'id': 'a'},
            'document': _doc(),
          };
        }
        return <String, dynamic>{};
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    // Факты страницы.
    await tester.tap(find.byKey(const Key('inspector-tab-page')));
    await tester.pump();
    expect(find.text('rapidocr'), findsOneWidget);
    expect(find.text('argos'), findsOneWidget);
    expect(find.byKey(const Key('page-retranslate')), findsOneWidget);

    // «Сбросить правки» — подтверждение и POST reset.
    await tester.tap(find.byKey(const Key('page-reset')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(const Key('page-reset-dialog')), findsOneWidget);
    await tester.tap(find.byKey(const Key('page-reset-confirm')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(
      host.requests.where((r) => r == 'POST /api/pages/a/reset'),
      hasLength(1),
    );

    // Прогон: вкладка «Отчёт» с счётчиками и повтором ошибок.
    expect(find.byKey(const Key('inspector-tab-report')), findsOneWidget);
    await tester.tap(find.byKey(const Key('inspector-tab-report')));
    await tester.pump();
    expect(find.text('Всего страниц'), findsOneWidget);
    expect(find.byKey(const Key('report-error-banner')), findsOneWidget);
    await tester.tap(find.byKey(const Key('report-retry')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(
      host.requests
          .where((r) => r == 'POST /api/jobs/retry-errors')
          .toList(),
      hasLength(1),
    );
  });
}
