import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';
import 'package:ilt_desktop/src/ui/theme.dart';
import 'package:ilt_desktop/src/ui/viewer/canvas_painter.dart';

/// Регрессия 027: painter рисует в координатах листа, transform применяет
/// только `InteractiveViewer`. Если painter снова начнёт применять матрицу,
/// штрих сместится в `scale × scene + t` (при 0.5 и 50 это 150 вместо 200).
void main() {
  test('ScenePainter: штрих в координатах листа при scale≠1 и сдвиге',
      () async {
    final viewer = ViewerState();
    final session = viewer.session;
    session.setImageSize(const Size(400, 400));
    session.setViewport(const Size(300, 300));
    session.setZoom(0.5);
    expect(session.transform.scale, 0.5);
    expect(session.transform.tx, 50);
    expect(session.transform.ty, 50);

    // Вид «Оригинал» без картинки не рисует плейсхолдер — на канвасе остаётся
    // только превью штриха (без подписи, которая маскировала бы пиксели).
    viewer.setView('original');
    session.beginStroke(Stroke.paint, const Offset(200, 200));

    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    ScenePainter(
      viewer: viewer,
      session: session,
      palette: IltPalette.dark,
    ).paint(canvas, const Size(300, 300));
    final image = await recorder.endRecording().toImage(300, 300);
    final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
    int green(int x, int y) => data.getUint8((y * 300 + x) * 4 + 1);

    expect(green(200, 200), greaterThan(60),
        reason: 'штрих обязан лежать в точке листа (200,200)');
    expect(green(150, 150), lessThan(60),
        reason: 'двойной transform нарисовал бы штрих в (150,150)');

    image.dispose();
    viewer.dispose();
  });

  test('ScenePainter: выключенная маска скрывает и цветной след', () async {
    final viewer = ViewerState();
    final session = viewer.session;
    session.setImageSize(const Size(400, 400));
    viewer.setView('original');
    viewer.setShowMask(false);
    final sizeRecorder = ui.PictureRecorder();
    Canvas(sizeRecorder);
    final sizeImage = await sizeRecorder.endRecording().toImage(400, 400);
    viewer.noteDisplayedImage(sizeImage);
    session.beginStroke(Stroke.paint, const Offset(200, 200));

    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    ScenePainter(
      viewer: viewer,
      session: session,
      palette: IltPalette.dark,
    ).paint(canvas, const Size(400, 400));
    final image = await recorder.endRecording().toImage(400, 400);
    final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
    expect(data.getUint8((200 * 400 + 200) * 4 + 1), lessThan(10));
    expect(data.getUint8((200 * 400 + 200) * 4 + 3), lessThan(10));

    image.dispose();
    sizeImage.dispose();
    viewer.dispose();
  });
}
