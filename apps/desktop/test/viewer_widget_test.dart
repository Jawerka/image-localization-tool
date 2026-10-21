import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/app.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/ui/viewer/canvas_view.dart';

import 'support/fake_host.dart';

Future<void> _scrollOver(WidgetTester tester, Key key, double dy) async {
  final center = tester.getCenter(find.byKey(key));
  await tester.sendEventToBinding(
    PointerScrollEvent(position: center, scrollDelta: Offset(0, dy)),
  );
  await tester.pump();
}

void main() {
  testWidgets('просмотрщик: канвас, чипы, док, пилюля и уход со страницы', (
    tester,
  ) async {
    sizeWindow(tester);
    final bootstrap = <String, dynamic>{
      'settings': settingsDone(<String, dynamic>{}),
      'project': {'id': 'pr', 'name': 'Глава'},
      'pages': [
        {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        {'id': 'b', 'name': '002.jpg', 'status': 'done', 'progress': 100},
      ],
    };
    final (state, host) = await readyHost(
      bootstrap: bootstrap,
      reply: (path, method) {
        if (path == '/api/pages/a' || path == '/api/pages/b') {
          return <String, dynamic>{
            'page': {'id': path.split('/').last},
            'document': {
              'version': 3,
              'regions': [
                {
                  'id': '1',
                  'bbox': [10, 10, 100, 100],
                  'overflow': true,
                },
              ],
              'strokes': <dynamic>[],
            },
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
    expect(find.byKey(const Key('scene-no-selection')), findsOneWidget);
    expect(find.byKey(const Key('viewer-dock')), findsNothing);

    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer-dock')), findsOneWidget);
    expect(find.byKey(const Key('viewer-mark-01 · 001.jpg')), findsOneWidget);
    expect(find.text('Регионов: 1'), findsOneWidget);
    expect(find.text('1 не влезает'), findsOneWidget);
    // 027: превью в рельсе; 028: превью ×1.3, строка 83, кнопка 48.
    expect(find.byKey(const Key('pages-thumb-a')), findsOneWidget);
    expect(
      tester.getSize(find.byKey(const Key('pages-thumb-a'))),
      const Size(55, 75),
    );
    expect(tester.getSize(find.byKey(const Key('page-row-a'))).height, 83);
    expect(
      tester.getSize(find.byKey(const Key('inspector-add-region'))).height,
      48,
    );

    // Переключение вида и слоёв из дока.
    await tester.tap(find.byKey(const Key('dock-view-compare')));
    await tester.pump();
    expect(state.workspace.viewer.view, 'compare');
    expect(state.workspace.viewer.curtain, closeTo(0.46, 1e-9));
    await tester.tap(find.byKey(const Key('dock-view-clean')));
    await tester.pump();
    expect(state.workspace.viewer.view, 'clean');
    await tester.tap(find.byKey(const Key('dock-boxes')));
    await tester.pump();
    expect(state.workspace.viewer.showBoxes, isFalse);

    // Зум кнопкой — режим становится числом.
    await tester.tap(find.byKey(const Key('dock-zoom-in')));
    await tester.pump();
    expect(state.workspace.viewer.session.zoomMode, isA<double>());

    // Правка → пилюля «N правок».
    state.workspace.viewer.editDocument(
      (document) => document.addStroke(
        const Stroke(mode: Stroke.paint, radius: 4, points: [Offset(1, 1)]),
      ),
      deferApply: true,
    );
    await tester.pump();
    expect(find.byKey(const Key('viewer-done-pill')), findsOneWidget);
    expect(find.textContaining('не применены'), findsOneWidget);

    // Уход со страницы с черновиком: диалог и «Остаться».
    await tester.tap(find.byKey(const Key('page-row-b')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer-leave-dialog')), findsOneWidget);
    await tester.tap(find.byKey(const Key('viewer-leave-stay')));
    await tester.pumpAndSettle();
    expect(state.workspace.activeId, 'a');

    // «Отменить правки» — документ перечитывается, страница меняется.
    await tester.tap(find.byKey(const Key('page-row-b')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('viewer-leave-discard')));
    await tester.pumpAndSettle();
    expect(state.workspace.activeId, 'b');
    expect(state.workspace.viewer.hasDeferredDraft, isFalse);
  });

  testWidgets('док перетаскивается к верхнему краю и сохраняется', (
    tester,
  ) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: <String, dynamic>{
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        ],
      },
      reply: (path, method) => path == '/api/pages/a'
          ? <String, dynamic>{
              'page': {'id': 'a'},
              'document': {
                'version': 1,
                'regions': <dynamic>[],
                'strokes': <dynamic>[],
              },
            }
          : <String, dynamic>{},
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer-dock-grip')), findsOneWidget);
    expect(state.workspace.dockAtTop, isFalse);
    // Вверх больше ⅓ высоты сцены — док уходит наверх и позиция сохраняется.
    await tester.drag(
      find.byKey(const Key('viewer-dock-grip')),
      const Offset(0, -500),
    );
    await tester.pumpAndSettle();
    expect(state.workspace.dockAtTop, isTrue);
    expect(host.requests, contains('PUT /api/settings'));
    expect(host.bodies.last, contains('"dock_position":"top"'));
    // Малый сдвиг вниз — сторона не меняется, PUT не дублируется.
    final putsBefore = host.requests
        .where((r) => r == 'PUT /api/settings')
        .length;
    await tester.drag(
      find.byKey(const Key('viewer-dock-grip')),
      const Offset(0, 40),
    );
    await tester.pumpAndSettle();
    expect(state.workspace.dockAtTop, isTrue);
    expect(
      host.requests.where((r) => r == 'PUT /api/settings').length,
      putsBefore,
    );
    // Вниз больше ⅓ — док возвращается к нижнему краю.
    await tester.drag(
      find.byKey(const Key('viewer-dock-grip')),
      const Offset(0, 500),
    );
    await tester.pumpAndSettle();
    expect(state.workspace.dockAtTop, isFalse);
    expect(host.bodies.last, contains('"dock_position":"bottom"'));
  });

  testWidgets('Space — временная «Рука»: курсор, инструмент, кружок кисти', (
    tester,
  ) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: <String, dynamic>{
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        ],
      },
      reply: (path, method) => path == '/api/pages/a'
          ? <String, dynamic>{
              'page': {'id': 'a'},
              'document': {
                'version': 1,
                'regions': <dynamic>[],
                'strokes': <dynamic>[],
              },
            }
          : <String, dynamic>{},
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();

    final viewer = state.workspace.viewer;
    viewer.setTool('brush');
    viewer.session.setCursor(const Offset(120, 120));
    await tester.pump();

    MouseRegion canvasRegion() => tester.widget<MouseRegion>(
      find.descendant(
        of: find.byType(CanvasView),
        matching: find.byType(MouseRegion),
      ),
    );
    expect(canvasRegion().cursor, SystemMouseCursors.precise);
    expect(find.byKey(const Key('viewer-brush-cursor')), findsOneWidget);

    // Space — временная рука: выбранный инструмент не меняется, кружок скрыт.
    await tester.sendKeyDownEvent(LogicalKeyboardKey.space);
    await tester.pump();
    expect(canvasRegion().cursor, SystemMouseCursors.grab);
    expect(viewer.tool, 'brush');
    expect(find.byKey(const Key('viewer-brush-cursor')), findsNothing);

    await tester.sendKeyUpEvent(LogicalKeyboardKey.space);
    await tester.pump();
    expect(canvasRegion().cursor, SystemMouseCursors.precise);
    expect(find.byKey(const Key('viewer-brush-cursor')), findsOneWidget);
  });

  testWidgets('заливка: кнопка, G и допуск', (tester) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: <String, dynamic>{
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
        ],
      },
      reply: (path, method) => path == '/api/pages/a'
          ? <String, dynamic>{
              'page': {'id': 'a'},
              'document': {
                'version': 1,
                'regions': <dynamic>[],
                'strokes': <dynamic>[],
              },
            }
          : <String, dynamic>{},
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();

    final viewer = state.workspace.viewer;
    await tester.tap(find.byKey(const Key('dock-tool-fill')));
    await tester.pumpAndSettle();
    expect(viewer.tool, 'fill');
    expect(find.byKey(const Key('dock-fill-tolerance')), findsOneWidget);
    expect(find.byKey(const Key('dock-brush-size')), findsNothing);

    await tester.tap(find.byKey(const Key('dock-fill-tolerance')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('dock-fill-slider')), findsOneWidget);

    final tolerance = viewer.fillTolerance;
    await _scrollOver(tester, const Key('dock-fill-tolerance'), -20);
    expect(viewer.fillTolerance, tolerance + 1);

    await tester.tap(find.byKey(const Key('dock-tool-brush')));
    await tester.pumpAndSettle();
    expect(viewer.tool, 'brush');
    expect(find.byKey(const Key('dock-brush-size')), findsOneWidget);
    final brush = viewer.brushSize;
    await _scrollOver(tester, const Key('dock-brush-size'), -20);
    expect(viewer.brushSize, brush + 1);
    await _scrollOver(tester, const Key('dock-brush-size'), 20);
    expect(viewer.brushSize, brush);

    await _scrollOver(tester, const Key('dock-tool-brush'), -20);
    expect(viewer.brushSize, brush + 1);

    await tester.sendKeyEvent(LogicalKeyboardKey.keyG);
    await tester.pump();
    expect(viewer.tool, 'fill');
  });

  testWidgets('вкладки «Страницы» и «Очередь» переключают содержимое', (
    tester,
  ) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: <String, dynamic>{
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'queued', 'progress': 0},
          {'id': 'b', 'name': '002.jpg', 'status': 'running', 'progress': 40},
          {'id': 'c', 'name': '003.jpg', 'status': 'done', 'progress': 100},
        ],
      },
    );
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.pump();

    expect(find.byKey(const Key('pages-tab-pages')), findsOneWidget);
    expect(find.byKey(const Key('pages-search')), findsOneWidget);
    // 049: во время обработки очередь не дублируется на «Страницах».
    expect(find.byKey(const Key('pages-batch')), findsNothing);
    await tester.tap(find.byKey(const Key('pages-tab-queue')));
    await tester.pump();
    expect(find.byKey(const Key('queue-list')), findsOneWidget);
    expect(find.byKey(const Key('pages-batch')), findsOneWidget);
    expect(find.byKey(const Key('pages-search')), findsNothing);
    await tester.tap(find.byKey(const Key('pages-tab-pages')));
    await tester.pump();
    expect(find.byKey(const Key('pages-search')), findsOneWidget);
    expect(find.byKey(const Key('pages-batch')), findsNothing);
  });

  testWidgets('слои: кнопки, клавиши, страница и регион сохраняются', (
    tester,
  ) async {
    sizeWindow(tester);
    final (state, host) = await readyHost(
      bootstrap: <String, dynamic>{
        'settings': settingsDone(<String, dynamic>{}),
        'project': {'id': 'pr', 'name': 'Глава'},
        'pages': [
          {'id': 'a', 'name': '001.jpg', 'status': 'done', 'progress': 100},
          {'id': 'b', 'name': '002.jpg', 'status': 'done', 'progress': 100},
        ],
      },
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
    addTearDown(() {
      state.dispose();
      host.events.close();
    });
    await tester.pumpWidget(IltApp(state: state));
    await tester.tap(find.byKey(const Key('page-row-a')));
    await tester.pumpAndSettle();
    final viewer = state.workspace.viewer;
    Map<String, dynamic> lastBody() {
      for (var i = host.requests.length - 1; i >= 0; i--) {
        if (host.requests[i] == 'PUT /api/settings') {
          return jsonDecode(host.bodies[i]) as Map<String, dynamic>;
        }
      }
      throw StateError('нет PUT /api/settings');
    }

    await tester.tap(find.byKey(const Key('dock-boxes')));
    await tester.pumpAndSettle();
    expect(viewer.showBoxes, isFalse);
    expect(lastBody()['viewer_show_boxes'], isFalse);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.keyL);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.keyL);
    await tester.pumpAndSettle();
    expect(viewer.showBoxes, isTrue);
    expect(lastBody()['viewer_show_boxes'], isTrue);

    await tester.sendKeyDownEvent(LogicalKeyboardKey.keyM);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.keyM);
    await tester.pumpAndSettle();
    expect(viewer.showMask, isFalse);
    expect(lastBody()['viewer_show_mask'], isFalse);

    // Смена страницы не сбрасывает выбор слоёв.
    await tester.tap(find.byKey(const Key('page-row-b')));
    await tester.pumpAndSettle();
    expect(viewer.showBoxes, isTrue);
    expect(viewer.showMask, isFalse);

    // Создание региона включает рамки и сохраняет включённое состояние.
    viewer.setShowBoxes(false);
    await tester.pumpAndSettle();
    viewer.addRegionAtViewCenter();
    await tester.pumpAndSettle();
    // Дать сработать отложенному preview, иначе остаётся pending timer.
    await tester.pump(const Duration(milliseconds: 500));
    expect(viewer.showBoxes, isTrue);
    expect(lastBody()['viewer_show_boxes'], isTrue);
  });
}
