// Spike-замер jank'а просмотрщика страницы (подготовка 023).
//
// Вопрос: тянет ли Flutter-хост отрисовку листа (большое изображение) с
// оверлеями регионов при панорамировании и зуме, и где должен жить transform —
// внутри paint дерева сцены или на отдельном слое («вне paint»).
//
// Варианты сцены:
//   widgets  — InteractiveViewer > Stack(RawImage + виджеты-рамки), без слоя;
//   boundary — то же, но содержимое сцены обёрнуто RepaintBoundary;
//   painter  — InteractiveViewer > RepaintBoundary > CustomPaint(лист и рамки);
//   split    — лист в RepaintBoundary под transform, оверлеи — отдельный
//              CustomPaint в экранных координатах (слушает TransformationController).
//
// Каждый вариант прогоняется через скриптованные фазы (без участия человека):
// панорама «вписано», дискретные шаги зума (как колесо у веб-версии),
// панорама 100 %, плавный зум. Во время фаз собираются FrameTiming
// (build/raster/total), по ним считается p50/p90/p99/max и число «слоу-фреймов».
//
// Запуск (профиль обязателен, иначе raster-времена не настоящие):
//   flutter run -d windows --profile -t tool/viewer_jank_spike.dart `
//     --dart-define=SPIKE_OUT=<абсолютный путь к json>
//
// Настройки через --dart-define:
//   SPIKE_IMAGE=001_eng.jpg        — имя/путь картинки (ищется в test-img/)
//   SPIKE_VARIANTS=widgets,boundary,painter,split (или all)
//   SPIKE_REGIONS=60,200           — сколько рамок-регионов
//   SPIKE_PHASE_SECONDS=3          — длительность записи фазы
//   SPIKE_WARMUP_SECONDS=1.2       — прогрев перед записью
//   SPIKE_SETTLE_SECONDS=0.8       — пауза между прогонами
//
// Результат: JSON в SPIKE_OUT (по умолчанию benchmark_results/viewer_jank.json)
// и короткие строки SPIKE … в stdout. Приложение завершается само.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

const String _imageArg =
    String.fromEnvironment('SPIKE_IMAGE', defaultValue: '001_eng.jpg');
const String _variantsArg =
    String.fromEnvironment('SPIKE_VARIANTS', defaultValue: 'all');
const String _regionsArg =
    String.fromEnvironment('SPIKE_REGIONS', defaultValue: '60,200');
const String _outArg = String.fromEnvironment('SPIKE_OUT', defaultValue: '');
const String _phaseSecondsArg =
    String.fromEnvironment('SPIKE_PHASE_SECONDS', defaultValue: '3');
const String _warmupSecondsArg =
    String.fromEnvironment('SPIKE_WARMUP_SECONDS', defaultValue: '1.2');
const String _settleSecondsArg =
    String.fromEnvironment('SPIKE_SETTLE_SECONDS', defaultValue: '0.8');

const List<String> _phaseNames = <String>[
  'pan_fit',
  'zoom_steps',
  'pan_100',
  'zoom_smooth',
];

/// Снимок одного кадра в миллисекундах.
typedef FrameSample = ({double buildMs, double rasterMs, double totalMs});

/// Вариант построения сцены.
enum SpikeVariant {
  widgets,
  boundary,
  painter,
  uncached,
  split;

  static SpikeVariant parse(String name) {
    for (final variant in SpikeVariant.values) {
      if (variant.name == name) {
        return variant;
      }
    }
    stderr.writeln('SPIKE_ERROR: неизвестный вариант «$name»');
    exit(2);
  }
}

/// Один прогон: вариант сцены и число регионов.
class SpikeRun {
  const SpikeRun(this.variant, this.regions);

  final SpikeVariant variant;
  final int regions;

  String get label => '${variant.name} r$regions';
}

/// Конфигурация замера.
class SpikeConfig {
  const SpikeConfig({
    required this.runs,
    required this.phaseMs,
    required this.warmupMs,
    required this.settleMs,
    required this.outPath,
  });

  final List<SpikeRun> runs;
  final int phaseMs;
  final int warmupMs;
  final int settleMs;
  final String outPath;

  static SpikeConfig fromEnvironment({required String defaultOutPath}) {
    final variants = _variantsArg.trim().toLowerCase() == 'all'
        ? SpikeVariant.values
        : _variantsArg
            .split(',')
            .map((name) => SpikeVariant.parse(name.trim()))
            .toList();
    final counts = _regionsArg
        .split(',')
        .map((value) => int.parse(value.trim()))
        .where((value) => value >= 0)
        .toList();
    if (counts.isEmpty) {
      stderr.writeln('SPIKE_ERROR: SPIKE_REGIONS пуст');
      exit(2);
    }
    return SpikeConfig(
      runs: <SpikeRun>[
        for (final variant in variants)
          for (final count in counts) SpikeRun(variant, count),
      ],
      phaseMs: (_seconds(_phaseSecondsArg, 3) * 1000).round(),
      warmupMs: (_seconds(_warmupSecondsArg, 1.2) * 1000).round(),
      settleMs: (_seconds(_settleSecondsArg, 0.8) * 1000).round(),
      outPath: _outArg.isEmpty ? defaultOutPath : _outArg,
    );
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final imageFile = _resolveImageFile();
  final image = await _decodeImage(imageFile);
  final repoRoot = imageFile.parent.parent.path;
  final config = SpikeConfig.fromEnvironment(
    defaultOutPath: <String>[
      repoRoot,
      'benchmark_results',
      'viewer_jank.json',
    ].join(Platform.pathSeparator),
  );
  stdout.writeln(
    'SPIKE_START image=${imageFile.path} '
    '${image.width}x${image.height} runs=${config.runs.length} '
    'phase=${config.phaseMs}ms out=${config.outPath}',
  );
  runApp(_SpikeApp(config: config, image: image, imagePath: imageFile.path));
}

/// Секунды из --dart-define с запасным значением.
double _seconds(String raw, double fallback) {
  final value = double.tryParse(raw);
  if (value == null || value <= 0) {
    return fallback;
  }
  return value;
}

/// Ищем картинку: абсолютный путь как есть, иначе `test-img/<имя>` вверх от cwd.
File _resolveImageFile() {
  final direct = File(_imageArg);
  if (direct.isAbsolute) {
    if (direct.existsSync()) {
      return direct;
    }
    stderr.writeln('SPIKE_ERROR: файл не найден: ${direct.path}');
    exit(2);
  }
  final name = _imageArg.split(RegExp(r'[\\/]')).last;
  var dir = Directory.current;
  for (var depth = 0; depth < 10; depth++) {
    final candidate = File(
      <String>[dir.path, 'test-img', name].join(Platform.pathSeparator),
    );
    if (candidate.existsSync()) {
      return candidate;
    }
    final parent = dir.parent;
    if (parent.path == dir.path) {
      break;
    }
    dir = parent;
  }
  stderr.writeln(
    'SPIKE_ERROR: не найден test-img/$name (cwd=${Directory.current.path})',
  );
  exit(2);
}

Future<ui.Image> _decodeImage(File file) async {
  final bytes = await file.readAsBytes();
  final codec = await ui.instantiateImageCodec(bytes);
  final frame = await codec.getNextFrame();
  return frame.image;
}

class _SpikeApp extends StatelessWidget {
  const _SpikeApp({
    required this.config,
    required this.image,
    required this.imagePath,
  });

  final SpikeConfig config;
  final ui.Image image;
  final String imagePath;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: _SpikeScreen(
        config: config,
        image: image,
        imagePath: imagePath,
      ),
    );
  }
}

enum _Stage { settle, warmup, record }

class _SpikeScreen extends StatefulWidget {
  const _SpikeScreen({
    required this.config,
    required this.image,
    required this.imagePath,
  });

  final SpikeConfig config;
  final ui.Image image;
  final String imagePath;

  @override
  State<_SpikeScreen> createState() => _SpikeScreenState();
}

class _SpikeScreenState extends State<_SpikeScreen>
    with SingleTickerProviderStateMixin {
  late final TransformationController _transform;
  late final Ticker _ticker;
  Timer? _watchdog;
  bool _done = false;

  final Map<int, List<_Region>> _regionCache = <int, List<_Region>>{};
  final List<FrameSample> _frames = <FrameSample>[];
  final List<Map<String, Object?>> _results = <Map<String, Object?>>[];

  int _runIndex = 0;
  int _phaseIndex = 0;
  _Stage _stage = _Stage.settle;
  int _stageStartMs = 0;
  int _phaseStartMs = 0;
  int _recordStartMs = 0;
  int _lastMs = 0;

  SpikeVariant _variant = SpikeVariant.widgets;
  List<_Region> _regions = const <_Region>[];
  Map<String, Object?>? _runResult;
  Size _viewport = Size.zero;
  double _refreshRate = 0;
  String _status = 'подготовка';

  @override
  void initState() {
    super.initState();
    _transform = TransformationController();
    _resetRun(0);
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
    _ticker = createTicker(_onTick)..start();
    _watchdog = Timer(const Duration(minutes: 15), _abort);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _refreshRate = View.of(context).display.refreshRate;
  }

  @override
  void dispose() {
    _watchdog?.cancel();
    _ticker.dispose();
    _transform.dispose();
    SchedulerBinding.instance.removeTimingsCallback(_onTimings);
    super.dispose();
  }

  void _onTimings(List<FrameTiming> timings) {
    if (_stage != _Stage.record) {
      return;
    }
    for (final timing in timings) {
      _frames.add((
        buildMs: timing.buildDuration.inMicroseconds / 1000.0,
        rasterMs: timing.rasterDuration.inMicroseconds / 1000.0,
        totalMs: timing.totalSpan.inMicroseconds / 1000.0,
      ));
    }
  }

  // ---- машина прогона ------------------------------------------------------

  void _resetRun(int index) {
    _runIndex = index;
    final run = widget.config.runs[index];
    _variant = run.variant;
    _regions = _regionsFor(run.regions);
    _phaseIndex = 0;
    _stage = _Stage.settle;
    _stageStartMs = _lastMs;
    _runResult = <String, Object?>{
      'variant': run.variant.name,
      'regions': run.regions,
      'phases': <String, Object?>{},
    };
    _status = '${run.label} · перед прогревом';
  }

  void _onTick(Duration elapsed) {
    if (_done) {
      return;
    }
    final ms = elapsed.inMilliseconds;
    _lastMs = ms;
    switch (_stage) {
      case _Stage.settle:
        _applyPhase(0);
        if (ms - _stageStartMs >= widget.config.settleMs) {
          _beginPhase();
        }
      case _Stage.warmup:
        _applyPhase(ms - _phaseStartMs);
        if (ms - _stageStartMs >= widget.config.warmupMs) {
          _stage = _Stage.record;
          _recordStartMs = ms;
          _frames.clear();
          _setStatus('запись');
        }
      case _Stage.record:
        _applyPhase(ms - _phaseStartMs);
        if (ms - _recordStartMs >= widget.config.phaseMs) {
          _finishPhase();
        }
    }
  }

  void _beginPhase() {
    setState(() {
      _stage = _Stage.warmup;
      _phaseStartMs = _lastMs;
      _stageStartMs = _lastMs;
      _setStatus('прогрев');
    });
  }

  void _finishPhase() {
    final phases = _runResult!['phases']! as Map<String, Object?>;
    phases[_phaseNames[_phaseIndex]] = _computeStats(_frames);
    stdout.writeln('SPIKE ${_runLabel()} ${_phaseNames[_phaseIndex]}: '
        '${_statsLine(_frames)}');
    _frames.clear();
    if (_phaseIndex + 1 < _phaseNames.length) {
      setState(() {
        _phaseIndex++;
        _stage = _Stage.warmup;
        _phaseStartMs = _lastMs;
        _stageStartMs = _lastMs;
        _setStatus('прогрев');
      });
    } else {
      _finishRun();
    }
  }

  void _finishRun() {
    _results.add(_runResult!);
    _writeResults(_payload(), announce: false);
    if (_runIndex + 1 < widget.config.runs.length) {
      setState(() => _resetRun(_runIndex + 1));
    } else {
      _finishAll();
    }
  }

  void _finishAll() {
    if (_done) {
      return;
    }
    _done = true;
    _ticker.stop();
    _watchdog?.cancel();
    _writeResults(_payload(), announce: true);
    stdout.writeln('SPIKE_DONE ${widget.config.outPath}');
    Timer(const Duration(milliseconds: 300), () => exit(0));
  }

  Map<String, Object?> _payload() {
    return <String, Object?>{
      'meta': <String, Object?>{
        'image': widget.imagePath,
        'natural': <int>[widget.image.width, widget.image.height],
        'scene': <double>[_viewport.width, _viewport.height],
        'refresh_hz': _refreshRate,
        'dpr': View.of(context).devicePixelRatio,
        'phase_ms': widget.config.phaseMs,
        'warmup_ms': widget.config.warmupMs,
        'dart': Platform.version,
        'os': Platform.operatingSystem,
        'measured_at': DateTime.now().toIso8601String(),
      },
      'runs': _results,
    };
  }

  void _abort() {
    if (_done) {
      return;
    }
    _done = true;
    _ticker.stop();
    stdout.writeln('SPIKE_ERROR таймаут: записаны неполные результаты');
    _writeResults(_payload(), announce: false);
    exit(3);
  }

  void _writeResults(Map<String, Object?> payload, {required bool announce}) {
    final json = const JsonEncoder.withIndent('  ').convert(payload);
    try {
      final file = File(widget.config.outPath);
      file.parent.createSync(recursive: true);
      file.writeAsStringSync(json);
    } on FileSystemException catch (error) {
      stderr.writeln('SPIKE_ERROR запись ${widget.config.outPath}: $error');
    }
    if (announce) {
      stdout.writeln('SPIKE_JSON $json');
    }
  }

  String _runLabel() {
    final run = widget.config.runs[_runIndex];
    return run.label;
  }

  void _setStatus(String stage) {
    _status = '${_runLabel()} · ${_phaseNames[_phaseIndex]} · $stage';
  }

  // ---- сцена ---------------------------------------------------------------

  List<_Region> _regionsFor(int count) {
    return _regionCache.putIfAbsent(count, () => _buildRegions(count));
  }

  List<_Region> _buildRegions(int count) {
    final random = math.Random(1234);
    final width = widget.image.width.toDouble();
    final height = widget.image.height.toDouble();
    final regions = <_Region>[];
    for (var index = 0; index < count; index++) {
      final w = width * (0.06 + random.nextDouble() * 0.24);
      final h = height * (0.04 + random.nextDouble() * 0.16);
      final x = random.nextDouble() * (width - w);
      final y = random.nextDouble() * (height - h);
      regions.add(_Region(
        rect: Rect.fromLTWH(x, y, w, h),
        number: index + 1,
      ));
    }
    return regions;
  }

  Widget _viewer(Widget child) {
    return InteractiveViewer(
      transformationController: _transform,
      constrained: false,
      minScale: 0.05,
      maxScale: 2.0,
      boundaryMargin: const EdgeInsets.all(double.infinity),
      child: child,
    );
  }

  Widget _scene() {
    final image = widget.image;
    final width = image.width.toDouble();
    final height = image.height.toDouble();
    switch (_variant) {
      case SpikeVariant.widgets:
      case SpikeVariant.boundary:
        Widget content = SizedBox(
          width: width,
          height: height,
          child: Stack(
            clipBehavior: Clip.none,
            children: <Widget>[
              Positioned.fill(
                child: RawImage(
                  image: image,
                  fit: BoxFit.fill,
                  filterQuality: FilterQuality.medium,
                ),
              ),
              for (final region in _regions)
                Positioned.fromRect(
                  rect: region.rect,
                  child: _BoxWidget(number: region.number),
                ),
            ],
          ),
        );
        if (_variant == SpikeVariant.boundary) {
          content = RepaintBoundary(child: content);
        }
        return _viewer(content);
      case SpikeVariant.painter:
        return _viewer(
          RepaintBoundary(
            child: SizedBox(
              width: width,
              height: height,
              child: CustomPaint(
                painter: _ScenePainter(image: image, regions: _regions),
              ),
            ),
          ),
        );
      case SpikeVariant.uncached:
        return _viewer(
          SizedBox(
            width: width,
            height: height,
            child: CustomPaint(
              painter: _ScenePainter(image: image, regions: _regions),
            ),
          ),
        );
      case SpikeVariant.split:
        return Stack(
          clipBehavior: Clip.none,
          children: <Widget>[
            Positioned.fill(
              child: _viewer(
                RepaintBoundary(
                  child: SizedBox(
                    width: width,
                    height: height,
                    child: RawImage(
                      image: image,
                      fit: BoxFit.fill,
                      filterQuality: FilterQuality.medium,
                    ),
                  ),
                ),
              ),
            ),
            Positioned.fill(
              child: IgnorePointer(
                child: AnimatedBuilder(
                  animation: _transform,
                  builder: (context, _) => CustomPaint(
                    painter: _OverlayPainter(
                      regions: _regions,
                      matrix: _transform.value,
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
    }
  }

  // ---- матрица фаз ---------------------------------------------------------

  void _applyPhase(int phaseMs) {
    if (_viewport.isEmpty) {
      return;
    }
    final width = widget.image.width.toDouble();
    final height = widget.image.height.toDouble();
    final vw = _viewport.width;
    final vh = _viewport.height;
    final fit = math.min(vw / width, vh / height) * 0.98;
    final t = phaseMs / 1000.0;
    double scale;
    double tx;
    double ty;
    switch (_phaseNames[_phaseIndex]) {
      case 'pan_fit':
        scale = fit;
        tx = (vw - width * scale) / 2 +
            0.22 * width * scale * math.sin(2 * math.pi * t / 2.5);
        ty = (vh - height * scale) / 2;
      case 'zoom_steps':
        const steps = <double>[0, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 1.5, 1.0, 0.75, 0.5, 0.35];
        final step = steps[(phaseMs ~/ 500) % steps.length];
        scale = math.min(2.0, math.max(0.05, step == 0 ? fit : step));
        tx = (vw - width * scale) / 2;
        ty = (vh - height * scale) / 2;
      case 'pan_100':
        scale = 1.0;
        tx = (vw - width) / 2 + 0.22 * width * math.sin(2 * math.pi * t / 2.5);
        ty = (vh - height) / 2;
      case 'zoom_smooth':
        scale = 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 3.0));
        tx = (vw - width * scale) / 2;
        ty = (vh - height * scale) / 2;
      default:
        scale = fit;
        tx = (vw - width * scale) / 2;
        ty = (vh - height * scale) / 2;
    }
    _transform.value = Matrix4.identity()
      ..setEntry(0, 0, scale)
      ..setEntry(1, 1, scale)
      ..setEntry(0, 3, tx)
      ..setEntry(1, 3, ty);
  }

  // ---- статистика ----------------------------------------------------------

  Map<String, Object?> _computeStats(List<FrameSample> frames) {
    if (frames.isEmpty) {
      return <String, Object?>{'frames': 0};
    }
    List<double> sorted(double Function(FrameSample) pick) {
      final values = frames.map(pick).toList()..sort();
      return values;
    }

    final build = sorted((sample) => sample.buildMs);
    final raster = sorted((sample) => sample.rasterMs);
    final total = sorted((sample) => sample.totalMs);
    double p(List<double> values, double q) =>
        values[math.min(values.length - 1, (values.length * q).floor())];
    int over(List<double> values, double threshold) =>
        values.where((value) => value > threshold).length;
    Map<String, double> triple(List<double> values) => <String, double>{
          'p50': _round2(p(values, 0.50)),
          'p90': _round2(p(values, 0.90)),
          'p99': _round2(p(values, 0.99)),
          'max': _round2(values.last),
        };
    return <String, Object?>{
      'frames': frames.length,
      'build': triple(build),
      'raster': triple(raster),
      'total': triple(total),
      'over_16_7': over(total, 16.7),
      'over_33_3': over(total, 33.3),
      'build_max_frame': _round2(build.last),
      'raster_max_frame': _round2(raster.last),
      'total_max_frame': _round2(total.last),
    };
  }

  String _statsLine(List<FrameSample> frames) {
    final stats = _computeStats(frames);
    if (frames.isEmpty) {
      return 'frames=0';
    }
    final total = stats['total']! as Map<String, double>;
    final raster = stats['raster']! as Map<String, double>;
    final build = stats['build']! as Map<String, double>;
    return 'frames=${frames.length} '
        'total[p50=${total['p50']} p99=${total['p99']} max=${total['max']}] '
        'raster[max=${raster['max']}] build[max=${build['max']}] '
        'jank>16.7=${stats['over_16_7']} severe>33.3=${stats['over_33_3']}';
  }

  static double _round2(double value) => (value * 100).round() / 100;

  // ---- вид ----------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF08090D),
      body: Column(
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                _status,
                style: const TextStyle(
                  color: Color(0xFFB7C2D0),
                  fontSize: 12,
                  fontFamily: 'monospace',
                ),
              ),
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: LayoutBuilder(
                builder: (context, constraints) {
                  _viewport = constraints.biggest;
                  return ClipRect(child: _scene());
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Регион листа: рамка и подпись-номер.
class _Region {
  _Region({required this.rect, required this.number});

  final Rect rect;
  final int number;

  late final TextPainter label = _buildLabel();

  TextPainter _buildLabel() {
    return TextPainter(
      text: TextSpan(
        text: '$number',
        style: const TextStyle(
          fontSize: 10.5,
          height: 1.0,
          fontWeight: FontWeight.w700,
          color: Color(0xFFF2F6FB),
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
  }
}

/// Виджет-рамка для вариантов widgets/boundary.
class _BoxWidget extends StatelessWidget {
  const _BoxWidget({required this.number});

  final int number;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(
          color: const Color(0xF2FFFFFF),
          width: 1.5,
        ),
      ),
      child: Align(
        alignment: Alignment.topLeft,
        child: FractionalTranslation(
          translation: const Offset(-0.5, -0.5),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 3),
            color: const Color(0xFF232C3F),
            child: Text(
              '$number',
              style: const TextStyle(
                fontSize: 10.5,
                height: 1.0,
                fontWeight: FontWeight.w700,
                color: Color(0xFFF2F6FB),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

final Paint _borderPaint = Paint()
  ..style = PaintingStyle.stroke
  ..strokeWidth = 1.5
  ..color = const Color(0xF2FFFFFF);

final Paint _chipPaint = Paint()..color = const Color(0xFF232C3F);

final Paint _imagePaint = Paint()..filterQuality = FilterQuality.medium;

/// Сцена одним пассом: лист и рамки в координатах листа (вариант painter).
class _ScenePainter extends CustomPainter {
  _ScenePainter({required this.image, required this.regions});

  final ui.Image image;
  final List<_Region> regions;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Rect.fromLTWH(
      0,
      0,
      image.width.toDouble(),
      image.height.toDouble(),
    );
    canvas.drawImageRect(image, rect, rect, _imagePaint);
    _paintRegions(canvas, regions, <Rect>[
      for (final region in regions) region.rect,
    ]);
  }

  @override
  bool shouldRepaint(_ScenePainter oldDelegate) =>
      oldDelegate.image != image || oldDelegate.regions != regions;
}

/// Оверлей в экранных координатах (вариант split): подписи и рамки не
/// масштабируются вместе с листом.
class _OverlayPainter extends CustomPainter {
  _OverlayPainter({required this.regions, required this.matrix});

  final List<_Region> regions;
  final Matrix4 matrix;

  @override
  void paint(Canvas canvas, Size size) {
    _paintRegions(canvas, regions, <Rect>[
      for (final region in regions) MatrixUtils.transformRect(matrix, region.rect),
    ]);
  }

  @override
  bool shouldRepaint(_OverlayPainter oldDelegate) =>
      oldDelegate.matrix != matrix || oldDelegate.regions != regions;
}

void _paintRegions(Canvas canvas, List<_Region> regions, List<Rect> rects) {
  for (var index = 0; index < regions.length; index++) {
    final rect = rects[index];
    canvas.drawRect(rect, _borderPaint);
    final chip = Rect.fromLTWH(rect.left - 9, rect.top - 9, 18, 18);
    canvas.drawRRect(
      RRect.fromRectAndRadius(chip, const Radius.circular(3)),
      _chipPaint,
    );
    regions[index].label.paint(canvas, chip.topLeft + const Offset(4.5, 3));
  }
}
