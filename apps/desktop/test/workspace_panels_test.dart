import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/ui/workspace_panels.dart';

void main() {
  testWidgets('обе панели возвращаются подписанными кнопками без проекта', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: WorkspacePanels(
            pages: SizedBox(width: 120, child: Text('Список страниц')),
            viewer: Text('Холст'),
            inspector: SizedBox(width: 120, child: Text('Свойства')),
          ),
        ),
      ),
    );
    expect(find.text('Скрыть страницы'), findsOneWidget);
    expect(find.text('Скрыть инспектор'), findsOneWidget);
    await tester.tap(find.byKey(const Key('workspace-toggle-pages')));
    await tester.tap(find.byKey(const Key('workspace-toggle-inspector')));
    await tester.pumpAndSettle();
    expect(find.text('Список страниц'), findsNothing);
    expect(find.text('Свойства'), findsNothing);
    expect(find.text('Показать страницы'), findsOneWidget);
    expect(find.text('Показать инспектор'), findsOneWidget);
    expect(find.text('Холст'), findsOneWidget);
    await tester.tap(find.text('Показать страницы'));
    await tester.tap(find.text('Показать инспектор'));
    await tester.pumpAndSettle();
    expect(find.text('Список страниц'), findsOneWidget);
    expect(find.text('Свойства'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('скрытие сохраняет ввод панели и исключает его из фокуса', (
    tester,
  ) async {
    final focus = FocusNode();
    addTearDown(focus.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: WorkspacePanels(
            pages: SizedBox(width: 160, child: TextField(focusNode: focus)),
            viewer: const Text('Холст'),
            inspector: const SizedBox(width: 120),
          ),
        ),
      ),
    );
    await tester.enterText(find.byType(TextField), 'Моя глава');
    await tester.tap(find.byKey(const Key('workspace-toggle-pages')));
    await tester.pumpAndSettle();
    expect(focus.canRequestFocus, isFalse);
    expect(find.byType(TextField), findsNothing);
    await tester.tap(find.text('Показать страницы'));
    await tester.pumpAndSettle();
    expect(find.text('Моя глава'), findsOneWidget);
    expect(focus.canRequestFocus, isTrue);
  });
}
