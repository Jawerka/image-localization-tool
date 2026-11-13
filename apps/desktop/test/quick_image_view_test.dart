import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/quick/quick_image_view.dart';

void main() {
  testWidgets(
    'колесо масштабирует под мышью, рука двигает, двойной клик сбрасывает',
    (tester) async {
      final pixels = base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGOQC+gBAAGKAPuTunr/AAAAAElFTkSuQmCC',
      );
      Widget view(String id) => MaterialApp(
        home: QuickImageView(key: ValueKey(id), pixels: pixels),
      );
      await tester.pumpWidget(view('one'));
      await tester.pumpAndSettle();
      TransformationController transform() => tester
          .widget<InteractiveViewer>(find.byType(InteractiveViewer))
          .transformationController!;
      const anchor = Offset(300, 200);
      final before = transform().toScene(anchor);
      await tester.sendEventToBinding(
        const PointerScrollEvent(
          position: anchor,
          scrollDelta: Offset(0, -120),
          kind: PointerDeviceKind.mouse,
        ),
      );
      await tester.pump();
      expect(transform().value.getMaxScaleOnAxis(), greaterThan(1));
      expect((transform().toScene(anchor) - before).distance, lessThan(0.001));
      final zoomed = transform().value.clone();
      final drag = await tester.startGesture(
        anchor,
        kind: PointerDeviceKind.mouse,
      );
      await drag.moveBy(const Offset(40, 30));
      await tester.pump();
      await drag.moveBy(const Offset(40, 30));
      await tester.pump();
      expect(
        tester
            .widget<MouseRegion>(
              find
                  .descendant(
                    of: find.byType(QuickImageView),
                    matching: find.byType(MouseRegion),
                  )
                  .first,
            )
            .cursor,
        SystemMouseCursors.grabbing,
      );
      await drag.up();
      await tester.pumpAndSettle();
      expect(transform().value, isNot(zoomed));
      expect(
        tester
            .widget<MouseRegion>(
              find
                  .descendant(
                    of: find.byType(QuickImageView),
                    matching: find.byType(MouseRegion),
                  )
                  .first,
            )
            .cursor,
        SystemMouseCursors.grab,
      );
      final panned = transform().value.clone();
      await tester.pumpWidget(view('one'));
      expect(transform().value, panned);
      await tester.tapAt(anchor);
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tapAt(anchor);
      await tester.pumpAndSettle();
      expect(transform().value, Matrix4.identity());
      await tester.sendEventToBinding(
        const PointerScrollEvent(
          position: anchor,
          scrollDelta: Offset(0, -120),
          kind: PointerDeviceKind.mouse,
        ),
      );
      await tester.pump();
      await tester.pumpWidget(view('two'));
      expect(transform().value, Matrix4.identity());
    },
  );
}
