import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' show Offset, Rect;

/// Модель документа страницы.
///
/// Сырой map сохраняется как есть (как `...raw` в `web/js/state.js`), известные
/// поля нормализуются. Мутации идут через [PageDocument.clone] + правку, чтобы
/// история undo/redo работала со снимками.
class PageDocument {
  PageDocument(this.data);

  /// Данные документа (версия, регионы, штрихи, предупреждения, тайминги).
  final Map<String, dynamic> data;

  factory PageDocument.fromJson(Map<String, dynamic> raw) =>
      PageDocument(normalizeDocument(raw));

  int get version => _int(data['version']);

  set version(int value) => data['version'] = value;

  List<String> get warnings => [
    for (final item in (data['warnings'] as List? ?? const [])) '$item',
  ];

  /// Живые представления регионов поверх тех же map'ов.
  List<Region> get regions {
    final raw = data['regions'];
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) Region(item.cast<String, dynamic>()),
    ];
  }

  List<Stroke> get strokes {
    final raw = data['strokes'];
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) Stroke.fromJson(item.cast<String, dynamic>()),
    ];
  }

  void addStroke(Stroke stroke) {
    final raw = data['strokes'];
    final list = raw is List ? List<dynamic>.from(raw) : <dynamic>[];
    list.add(stroke.toJson());
    data['strokes'] = list;
  }

  Region? findRegion(String? id) {
    if (id == null) return null;
    for (final region in regions) {
      if (region.id == id) return region;
    }
    return null;
  }

  /// Следующий числовой id (как `nextRegionId` в вебе).
  int nextRegionId() {
    var maxId = 0;
    for (final region in regions) {
      final value = int.tryParse(region.id);
      if (value != null && value > maxId) maxId = value;
    }
    return maxId + 1;
  }

  bool get hasOverflow => regions.any((region) => region.overflow);

  int get overflowCount => regions.where((region) => region.overflow).length;

  /// Ключ содержимого без версии — для истории и skip-пустых правок.
  String contentKey() {
    final copy = clone().data..remove('version');
    return jsonEncode(copy);
  }

  PageDocument clone() => PageDocument(deepCopyMap(data));

  Map<String, dynamic> toJson() => data;
}

/// Регион поверх сырого map (все неизвестные поля сохраняются при PUT).
class Region {
  Region(this.data);

  final Map<String, dynamic> data;

  String get id => '${data['id'] ?? ''}';

  String get type => '${data['type'] ?? data['block_type'] ?? 'dialogue'}';

  bool get isSfx => type == 'sfx';

  bool get skip => data['skip'] == true;

  set skip(bool value) => data['skip'] = value;

  bool get overflow => data['overflow'] == true;

  bool get edited => data['edited'] == true;

  set edited(bool value) => data['edited'] = value;

  int get order => _int(data['order']);

  set order(int value) => data['order'] = value;

  Rect get bbox {
    final raw = data['bbox'];
    if (raw is! List || raw.length < 4) return Rect.zero;
    return Rect.fromLTWH(
      _double(raw[0]),
      _double(raw[1]),
      _double(raw[2]),
      _double(raw[3]),
    );
  }

  set bbox(Rect value) =>
      data['bbox'] = [value.left, value.top, value.width, value.height];

  /// Область баллона, если сервер её вернул; иначе null.
  Rect? get bubbleBbox {
    final raw = data['bubble_bbox'];
    if (raw is! List || raw.length < 4) return null;
    return Rect.fromLTWH(
      _double(raw[0]),
      _double(raw[1]),
      _double(raw[2]),
      _double(raw[3]),
    );
  }

  /// Независимый якорь текста в координатах страницы (038).
  Offset? get textPosition {
    final raw = data['text_position'];
    if (raw is! List || raw.length < 2) return null;
    if (raw[0] is! num || raw[1] is! num) return null;
    return Offset(_double(raw[0]), _double(raw[1]));
  }

  set textPosition(Offset? value) =>
      data['text_position'] = value == null ? null : [value.dx, value.dy];

  /// Стиль: живой map (создаётся при первой правке).
  Map<String, dynamic> styleMap({bool create = false}) {
    final raw = data['style'];
    if (raw is Map) return raw.cast<String, dynamic>();
    if (!create) return const {};
    final style = <String, dynamic>{
      'fill_rgb': [0, 0, 0],
      'stroke_rgb': null,
      'font_size': 16,
      'alignment': 'center',
      'uppercase': false,
      'line_height': 18,
      'font_size_override': 0,
    };
    data['style'] = style;
    return style;
  }

  double get rotation {
    final style = data['style'];
    if (style is! Map) return 0;
    return _double(style['rotation']);
  }

  set rotation(double value) => styleMap(create: true)['rotation'] = value;

  /// Искажение: `{kind, bend, quad, mesh}`.
  Map<String, dynamic>? get warp {
    final style = data['style'];
    if (style is! Map) return null;
    final raw = style['warp'];
    if (raw is! Map) return null;
    return raw.cast<String, dynamic>();
  }

  void setWarp(Map<String, dynamic> value) =>
      styleMap(create: true)['warp'] = value;

  /// Дефолтные точки quad-искажения (4 угла bbox).
  static List<List<double>> defaultQuad(double w, double h) => [
    [0, 0],
    [w, 0],
    [w, h],
    [0, h],
  ];

  /// Дефолтная mesh-сетка 4×4.
  static List<List<double>> defaultMesh(double w, double h) {
    final points = <List<double>>[];
    for (var row = 0; row < 4; row++) {
      for (var col = 0; col < 4; col++) {
        points.add([col * w / 3, row * h / 3]);
      }
    }
    return points;
  }
}

/// Штрих маски: кисть (`paint`/`erase`) или заливка лассо (`fill`/`erase_fill`).
class Stroke {
  const Stroke({
    required this.mode,
    required this.radius,
    required this.points,
  });

  final String mode;
  final double radius;
  final List<Offset> points;

  static const paint = 'paint';
  static const erase = 'erase';
  static const fill = 'fill';
  static const eraseFill = 'erase_fill';

  factory Stroke.fromJson(Map<String, dynamic> json) {
    final rawPoints = json['points'];
    return Stroke(
      mode: _normalizeStrokeMode(json['mode']),
      radius: math.max(1, _double(json['radius'])),
      points: [
        if (rawPoints is List)
          for (final point in rawPoints)
            if (point is List && point.length >= 2)
              Offset(_double(point[0]), _double(point[1])),
      ],
    );
  }

  Map<String, dynamic> toJson() => {
    'mode': mode,
    'radius': radius,
    'points': [
      for (final point in points) [point.dx, point.dy],
    ],
  };
}

/// Нормализация документа (зеркало `normalizeDocument` в web/js/state.js).
Map<String, dynamic> normalizeDocument(Map<String, dynamic> raw) {
  final data = <String, dynamic>{...raw};
  data['version'] = _int(data['version']);
  final regionsRaw = data['regions'];
  data['regions'] = <Map<String, dynamic>>[
    if (regionsRaw is List)
      for (final item in regionsRaw)
        if (item is Map) normalizeRegion(item.cast<String, dynamic>()),
  ];
  final strokesRaw = data['strokes'];
  data['strokes'] = <Map<String, dynamic>>[
    if (strokesRaw is List)
      for (final item in strokesRaw)
        if (item is Map) Stroke.fromJson(item.cast<String, dynamic>()).toJson(),
  ];
  data['reading_direction'] = data['reading_direction'] ?? 'ltr';
  final warningsRaw = data['warnings'];
  data['warnings'] = <String>[
    if (warningsRaw is List)
      for (final item in warningsRaw) '$item',
  ];
  final timings = data['timings'];
  data['timings'] = timings is Map ? {...timings} : <String, dynamic>{};
  data['ocr_engine'] = data['ocr_engine'] ?? '';
  data['translator_engine'] = data['translator_engine'] ?? '';
  return data;
}

/// Нормализация региона (зеркало `normalizeRegion`).
Map<String, dynamic> normalizeRegion(Map<String, dynamic> raw) {
  final data = <String, dynamic>{...raw};
  data['id'] = '${data['id'] ?? ''}';
  final bbox = data['bbox'];
  data['bbox'] = bbox is List && bbox.length >= 4
      ? [for (var i = 0; i < 4; i++) _double(bbox[i])]
      : <double>[0, 0, 0, 0];
  data['text'] = data['text'] == null ? '' : '${data['text']}';
  data['translation'] = data['translation'] == null
      ? ''
      : '${data['translation']}';
  final type = data['type'] ?? data['block_type'] ?? 'dialogue';
  data['type'] = type;
  data['block_type'] = type;
  data['speaker'] = data['speaker'] == null ? '' : '${data['speaker']}';
  data['skip'] = data['skip'] == true;
  data['manual'] = data['manual'] == true;
  data['edited'] = data['edited'] == true;
  data['overflow'] = data['overflow'] == true;
  data['translation_locked'] = data['translation_locked'] == true;
  final styleRaw = data['style'];
  final style = styleRaw is Map
      ? styleRaw.cast<String, dynamic>().map(
          (key, value) => MapEntry(key, value),
        )
      : <String, dynamic>{};
  style.putIfAbsent('font_size_override', () => 0);
  style.putIfAbsent('uppercase', () => false);
  data['style'] = style;
  return data;
}

/// Новый пустой регион (зеркало `blankRegion`).
Map<String, dynamic> blankRegion(int id, Rect bbox) => {
  'id': id,
  'bbox': [bbox.left, bbox.top, bbox.width, bbox.height],
  'class_name': 'text_free',
  'confidence': 1,
  'text': '',
  'translation': '',
  'type': 'dialogue',
  'block_type': 'dialogue',
  'speaker': '',
  'speaker_gender': '',
  'bubble_bbox': null,
  'order': 0,
  'skip': false,
  'manual': true,
  'edited': true,
  'overflow': false,
  'translation_locked': false,
  'style': {
    'fill_rgb': [0, 0, 0],
    'stroke_rgb': null,
    'font_size': 16,
    'alignment': 'center',
    'uppercase': false,
    'line_height': 18,
    'font_size_override': 0,
  },
};

/// Кламп bbox по границам листа (зеркало `clampBox`): минимум 4 px.
Rect clampBox(Rect box, double width, double height) {
  var w = math.max(4.0, box.width.roundToDouble());
  var h = math.max(4.0, box.height.roundToDouble());
  var x = box.left.roundToDouble();
  var y = box.top.roundToDouble();
  if (width > 0) {
    w = math.min(w, width);
    x = math.min(math.max(0, x), math.max(0, width - w));
  } else {
    x = math.max(0, x);
  }
  if (height > 0) {
    h = math.min(h, height);
    y = math.min(math.max(0, y), math.max(0, height - h));
  } else {
    y = math.max(0, y);
  }
  return Rect.fromLTWH(x, y, w, h);
}

/// Глубокая копия map/списков (без jsonEncode — штрихи бывают большими).
Map<String, dynamic> deepCopyMap(Map<String, dynamic> source) {
  final out = <String, dynamic>{};
  source.forEach((key, value) => out[key] = deepCopy(value));
  return out;
}

dynamic deepCopy(dynamic value) {
  if (value is Map) {
    return <String, dynamic>{
      for (final entry in value.entries) '${entry.key}': deepCopy(entry.value),
    };
  }
  if (value is List) return [for (final item in value) deepCopy(item)];
  return value;
}

String _normalizeStrokeMode(Object? raw) {
  final value = '${raw ?? ''}';
  if (value == 'erase' || value == 'erase_fill' || value == 'fill') {
    return value;
  }
  return Stroke.paint;
}

int _int(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

double _double(Object? value) {
  if (value is num) return value.toDouble();
  return double.tryParse('$value') ?? 0;
}
