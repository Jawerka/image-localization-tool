import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/app.dart';

void main() {
  testWidgets('ошибка каталога данных подсказывает перенести portable', (
    tester,
  ) async {
    await tester.pumpWidget(const StartupErrorApp());
    expect(
      find.byKey(const Key('startup-data-root-error')),
      findsOneWidget,
    );
    expect(find.textContaining('portable'), findsOneWidget);
    expect(find.textContaining('доступную для записи'), findsOneWidget);
  });
}
