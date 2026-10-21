import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/sidecar/window_geometry.dart';

const _display1 = r'\\.\DISPLAY1';
const _display2 = r'\\.\DISPLAY2';

const _work1 = Rect.fromLTWH(0, 0, 1920, 1040);

WindowGeometry _geometry({
  String monitor = _display1,
  int dpi = 96,
  Rect work = _work1,
  Rect normal = const Rect.fromLTWH(100, 80, 960, 600),
  bool maximized = false,
}) => WindowGeometry(
  monitor: monitor,
  dpi: dpi,
  work: work,
  normal: normal,
  maximized: maximized,
);

const _screen1 = ScreenInfo(
  name: _display1,
  work: _work1,
  dpi: 96,
  primary: true,
);

void main() {
  test('DPI 125 -> 150 keeps logical size and offsets', () {
    final result = resolvePlacement(_geometry(dpi: 120), const [
      ScreenInfo(name: _display1, work: _work1, dpi: 144, primary: true),
    ]);
    expect(result.rect, const Rect.fromLTWH(120, 96, 1152, 720));
    expect(result.maximized, isFalse);
  });

  test('changed resolution moves proportionally inside the same monitor', () {
    final result = resolvePlacement(
      _geometry(
        work: const Rect.fromLTWH(0, 0, 1920, 1040),
        normal: const Rect.fromLTWH(960, 520, 800, 600),
      ),
      const [
        ScreenInfo(
          name: _display1,
          work: Rect.fromLTWH(0, 0, 2560, 1400),
          dpi: 96,
          primary: true,
        ),
      ],
    );
    expect(result.rect, const Rect.fromLTWH(1280, 700, 800, 600));
  });

  test('negative coordinates of a left monitor survive', () {
    const work = Rect.fromLTWH(-2560, 0, 2560, 1400);
    final result = resolvePlacement(
      _geometry(
        monitor: _display2,
        work: work,
        normal: const Rect.fromLTWH(-2460, 80, 1280, 800),
      ),
      const [
        ScreenInfo(name: _display2, work: work, dpi: 96, primary: true),
      ],
    );
    expect(result.rect, const Rect.fromLTWH(-2460, 80, 1280, 800));
  });

  test('missing monitor falls back to primary proportionally', () {
    final result = resolvePlacement(
      _geometry(
        monitor: _display2,
        work: const Rect.fromLTWH(-2560, 0, 2560, 1400),
        normal: const Rect.fromLTWH(-2000, 200, 1000, 700),
      ),
      const [_screen1],
    );
    expect(result.rect, const Rect.fromLTWH(420, 149, 1000, 700));
  });

  test('window is shifted inside the work area', () {
    final result = resolvePlacement(
      _geometry(normal: const Rect.fromLTWH(1800, 900, 1200, 800)),
      const [_screen1],
    );
    expect(result.rect, const Rect.fromLTWH(720, 240, 1200, 800));
  });

  test('window larger than the work area is clamped to it', () {
    final result = resolvePlacement(
      _geometry(normal: const Rect.fromLTWH(100, 100, 3000, 2000)),
      const [_screen1],
    );
    expect(result.rect, _work1);
  });

  test('maximized flag is preserved', () {
    final result = resolvePlacement(_geometry(maximized: true), const [
      _screen1,
    ]);
    expect(result.maximized, isTrue);
  });

  test('JSON round trip', () {
    final original = _geometry(
      monitor: _display2,
      dpi: 144,
      work: const Rect.fromLTWH(-2560, 0, 2560, 1400),
      normal: const Rect.fromLTWH(-2000, 100, 1280, 800),
      maximized: true,
    );
    final restored = WindowGeometry.fromJson(original.toJson());
    expect(restored?.toJson(), original.toJson());
  });

  test('corrupt JSON is rejected', () {
    expect(WindowGeometry.fromJson(null), isNull);
    expect(WindowGeometry.fromJson({'version': 2}), isNull);
    expect(
      WindowGeometry.fromJson({
        'version': 1,
        'monitor': _display1,
        'dpi': 96,
        'work': [0, 0, 0, 100],
        'normal': [0, 0, 100, 100],
      }),
      isNull,
    );
    expect(
      WindowGeometry.fromJson({
        'version': 1,
        'monitor': _display1,
        'dpi': 96,
        'work': [0, 0, 100, 100],
        'normal': [double.nan, 0, 100, 100],
      }),
      isNull,
    );
  });
}
