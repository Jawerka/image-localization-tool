import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/ui/viewer/mask_overlay_painter.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const width = 40;
  const height = 20;

  Future<ui.Image> maskImage() =>
      _image(2, 1, [0, 0, 0, 255, 255, 255, 255, 255]);

  Future<Uint8List> render(
    MaskOverlayPainter painter, {
    int w = width,
    int h = height,
  }) async {
    final recorder = ui.PictureRecorder();
    final canvas = Canvas(recorder);
    canvas.drawRect(
      Rect.fromLTWH(0, 0, w.toDouble(), h.toDouble()),
      Paint()..color = const Color(0xFFFFFFFF),
    );
    painter.paint(canvas);
    final image = await recorder.endRecording().toImage(w, h);
    final data = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
    image.dispose();
    return data.buffer.asUint8List();
  }

  (int, int, int) pixel(Uint8List data, int x, int y, {int w = width}) {
    final offset = (y * w + x) * 4;
    return (data[offset], data[offset + 1], data[offset + 2]);
  }

  void expectPixel(Uint8List data, int x, int y, int r, int g, int b) {
    final value = pixel(data, x, y);
    expect(value.$1, closeTo(r, 2));
    expect(value.$2, closeTo(g, 2));
    expect(value.$3, closeTo(b, 2));
  }

  test('чёрная половина затемняет, белая прозрачна', () async {
    final data = await render(
      MaskOverlayPainter(
        mask: await maskImage(),
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [],
      ),
    );
    expectPixel(data, 10, 10, 128, 128, 128);
    expectPixel(data, 30, 10, 255, 255, 255);
  });

  test('серый сохраняет градацию', () async {
    final mask = await _image(1, 1, [128, 128, 128, 255]);
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [],
      ),
    );
    final value = pixel(data, 20, 10).$1;
    expect(value, greaterThan(160));
    expect(value, lessThan(220));
  });

  test('зелёный заменяет чёрный, красный виден на белом', () async {
    final mask = await maskImage();
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [
          Stroke(mode: Stroke.paint, radius: 5, points: [Offset(10, 10)]),
          Stroke(mode: Stroke.erase, radius: 5, points: [Offset(30, 10)]),
        ],
      ),
    );
    expectPixel(data, 10, 10, 200, 247, 200);
    expectPixel(data, 30, 10, 255, 204, 204);
    expectPixel(data, 20, 10, 255, 255, 255);
  });

  test(
    'повторные и пересекающиеся мазки не накапливают прозрачность',
    () async {
      final mask = await maskImage();
      final data = await render(
        MaskOverlayPainter(
          mask: mask,
          bounds: const Rect.fromLTWH(0, 0, 40, 20),
          strokes: const [
            Stroke(mode: Stroke.erase, radius: 6, points: [Offset(10, 10)]),
            Stroke(mode: Stroke.paint, radius: 6, points: [Offset(10, 10)]),
            Stroke(mode: Stroke.paint, radius: 6, points: [Offset(10, 10)]),
            Stroke(mode: Stroke.paint, radius: 6, points: [Offset(10, 10)]),
          ],
        ),
      );
      expectPixel(data, 10, 10, 200, 247, 200);
    },
  );

  test('линия и заливки рисуются в порядке списка', () async {
    final mask = await maskImage();
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [
          Stroke(
            mode: Stroke.fill,
            radius: 1,
            points: [
              Offset(2, 2),
              Offset(38, 2),
              Offset(38, 18),
              Offset(2, 18),
            ],
          ),
          Stroke(
            mode: Stroke.eraseFill,
            radius: 1,
            points: [
              Offset(5, 5),
              Offset(15, 5),
              Offset(15, 15),
              Offset(5, 15),
            ],
          ),
          Stroke(
            mode: Stroke.paint,
            radius: 2,
            points: [Offset(20, 4), Offset(30, 16)],
          ),
        ],
      ),
    );
    expectPixel(data, 30, 10, 200, 247, 200);
    expectPixel(data, 10, 10, 255, 204, 204);
  });

  test('пустая геометрия и полигон из двух точек не рисуются', () async {
    final mask = await maskImage();
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [
          Stroke(mode: Stroke.paint, radius: 4, points: []),
          Stroke(
            mode: Stroke.fill,
            radius: 1,
            points: [Offset(2, 2), Offset(30, 2)],
          ),
        ],
      ),
    );
    expectPixel(data, 10, 10, 128, 128, 128);
  });

  test('пустые границы ничего не рисуют', () async {
    final data = await render(
      MaskOverlayPainter(
        mask: await maskImage(),
        bounds: Rect.zero,
        strokes: const [
          Stroke(mode: Stroke.paint, radius: 20, points: [Offset(10, 10)]),
        ],
      ),
    );
    expectPixel(data, 10, 10, 255, 255, 255);
  });

  test('запечённые штрихи скрыты, новые и активный — цветные', () async {
    final mask = await maskImage();
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [
          Stroke(mode: Stroke.paint, radius: 5, points: [Offset(10, 10)]),
          Stroke(mode: Stroke.erase, radius: 5, points: [Offset(30, 10)]),
        ],
        bakedStrokeCount: 1,
        activeStroke: const Stroke(
          mode: Stroke.paint,
          radius: 4,
          points: [Offset(20, 10)],
        ),
      ),
    );
    expectPixel(data, 10, 10, 128, 128, 128);
    expectPixel(data, 30, 10, 255, 204, 204);
    expectPixel(data, 20, 10, 200, 247, 200);
  });

  test('активный мазок рисуется последним', () async {
    final mask = await maskImage();
    final data = await render(
      MaskOverlayPainter(
        mask: mask,
        bounds: const Rect.fromLTWH(0, 0, 40, 20),
        strokes: const [
          Stroke(mode: Stroke.paint, radius: 6, points: [Offset(10, 10)]),
        ],
        activeStroke: const Stroke(
          mode: Stroke.erase,
          radius: 6,
          points: [Offset(10, 10)],
        ),
      ),
    );
    expectPixel(data, 10, 10, 255, 204, 204);
  });
}

Future<ui.Image> _image(int width, int height, List<int> rgba) {
  final completer = Completer<ui.Image>();
  ui.decodeImageFromPixels(
    Uint8List.fromList(rgba),
    width,
    height,
    ui.PixelFormat.rgba8888,
    completer.complete,
  );
  return completer.future;
}
