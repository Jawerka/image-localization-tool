import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/model/page_document.dart';

void main() {
  final fixtureFile = File('test/../../tests/fixtures/page_document_contract.json');
  final alt = File('../../tests/fixtures/page_document_contract.json');
  final path = fixtureFile.existsSync()
      ? fixtureFile
      : (alt.existsSync() ? alt : File('../tests/fixtures/page_document_contract.json'));

  test('общий fixture сохраняет геометрию и неизвестные поля', () {
    final payload = jsonDecode(path.readAsStringSync()) as Map<String, dynamic>;
    final documents = payload['documents'] as List<dynamic>;
    for (final item in documents) {
      final map = item as Map<String, dynamic>;
      final raw = Map<String, dynamic>.from(map['document'] as Map);
      final document = PageDocument.fromJson(raw);
      final region = document.regions.first;
      final original = (raw['regions'] as List).first as Map;
      final position = original['text_position'];
      if (position is List && position.length == 2) {
        expect(region.data['text_position'], position);
      }
      if (original.containsKey('custom_client_field')) {
        expect(region.data['custom_client_field'], original['custom_client_field']);
      }
      if (original.containsKey('mystery')) {
        expect(region.data['mystery'], original['mystery']);
      }
      if (raw.containsKey('future_flag')) {
        expect(document.data['future_flag'], 'keep-me');
      }
      final style = original['style'];
      if (style is Map && style['warp'] is Map) {
        expect(region.warp?['version'], (style['warp'] as Map)['version']);
        expect(region.warp?['kind'], (style['warp'] as Map)['kind']);
      }
    }
  });
}
