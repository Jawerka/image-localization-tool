import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/ui/viewer/canvas_geometry.dart';

void main() {
  test('shared warp fixture matches Dart local surface', () {
    final fixtureFile = [
      File('../../tests/fixtures/local_warp_samples.json'),
      File('tests/fixtures/local_warp_samples.json'),
    ].firstWhere((file) => file.existsSync());
    final fixture =
        jsonDecode(fixtureFile.readAsStringSync()) as Map<String, dynamic>;
    final indices = (fixture['indices'] as List).cast<int>();
    final kinds = fixture['kinds'] as Map<String, dynamic>;
    for (final entry in kinds.entries) {
      final expected = (entry.value as List)
          .map((item) => (item as List).cast<num>())
          .toList();
      final surface = buildWarpSurface(
        kind: entry.key,
        width: (fixture['width'] as num).toDouble(),
        height: (fixture['height'] as num).toDouble(),
        origin: Offset.zero,
        bend: (fixture['bend'] as num).toDouble(),
        columns: fixture['columns'] as int,
        rows: fixture['rows'] as int,
      );
      for (var i = 0; i < indices.length; i++) {
        final point = surface.positions[indices[i]];
        expect(point.dx, closeTo(expected[i][0].toDouble(), 1e-3));
        expect(point.dy, closeTo(expected[i][1].toDouble(), 1e-3));
      }
    }
  });
}
