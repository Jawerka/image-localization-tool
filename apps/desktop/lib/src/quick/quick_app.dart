import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import 'quick_image_view.dart';
import 'window_bridge.dart';

import '../api/errors.dart';
import '../api/ilt_api.dart';
import '../ui/platform.dart' as platform;

const _stages = {
  'load': 'Ищем текст',
  'detect': 'Ищем текст',
  'ocr': 'Распознаём',
  'translate': 'Переводим',
  'segment': 'Стираем оригинал',
  'inpaint': 'Стираем оригинал',
  'typeset': 'Вписываем перевод',
};

/// Состояние только быстрого окна: без WorkspaceState и проекта редактора.
class QuickController extends ChangeNotifier {
  QuickController(this.api);

  final IltApi api;
  final viewTransform = TransformationController();
  List<Map<String, dynamic>> items = [];
  String selected = '';
  bool busy = false;
  bool original = false;
  String error = '';
  Uint8List? pixels;
  Map<String, dynamic> server = {};
  Timer? _timer;
  bool _refreshing = false;
  bool _disposed = false;
  int _epoch = 0;
  String _imageKey = '';
  String _snapshotKey = '';
  String _lastBadge = '';
  bool _transportError = false;
  final Map<String, DateTime> _completed = {};

  Map<String, dynamic>? get current {
    for (final item in items) {
      if (item['id'] == selected) return item;
    }
    return null;
  }

  String get stage => _stages[current?['stage']] ?? 'Переводим';
  String get badge {
    final item = current;
    switch (item?['status']) {
      case 'queued':
        return 'В очереди ${item?['queue_position'] ?? 1}';
      case 'running':
        return '${item?['progress'] ?? 0}%';
      case 'error':
        return '!';
      case 'cancelled':
        return 'Отменено';
      case 'done':
        final at = _completed[selected];
        return at != null && DateTime.now().difference(at).inSeconds < 2
            ? '✓'
            : '';
      default:
        return '';
    }
  }

  void start() {
    unawaited(refresh());
    _timer = Timer.periodic(
      const Duration(milliseconds: 500),
      (_) => refresh(),
    );
  }

  Future<void> refresh() async {
    if (_refreshing || _disposed) return;
    _refreshing = true;
    final epoch = _epoch;
    try {
      final payload = await api.getJson('/api/quick/session');
      if (_transportError) {
        error = '';
        _snapshotKey = '';
        _transportError = false;
      }
      if (epoch == _epoch && !_disposed) await _apply(payload);
    } catch (e) {
      if (!_disposed) {
        error = e is ApiException ? apiErrorMessage(e) : '$e';
        _transportError = true;
        notifyListeners();
      }
    } finally {
      _refreshing = false;
    }
  }

  Future<Map<String, dynamic>> action(
    String action, [
    Map<String, dynamic>? extra,
  ]) async {
    _epoch++;
    final payload = await api.postJson('/api/quick/$action', {
      'id': selected,
      ...?extra,
    });
    error = '';
    _snapshotKey = '';
    if (payload['items'] is List && !_disposed) await _apply(payload);
    if (!_disposed) notifyListeners();
    return payload;
  }

  Future<void> _apply(Map<String, dynamic> payload) async {
    final snapshotKey = jsonEncode(payload);
    if (snapshotKey == _snapshotKey && badge == _lastBadge) return;
    final next = (payload['items'] as List? ?? [])
        .cast<Map>()
        .map((x) => x.cast<String, dynamic>())
        .toList();
    for (final item in next) {
      if (item['status'] == 'done') {
        _completed.putIfAbsent('${item['id']}', DateTime.now);
      } else {
        _completed.remove('${item['id']}');
      }
    }
    final nextSelected = '${payload['selected_id'] ?? ''}';
    if (nextSelected != selected) {
      viewTransform.value = Matrix4.identity();
      original = false;
      error = '';
    }
    selected = nextSelected;
    items = next;
    busy = payload['busy'] == true;
    server = (payload['server'] as Map? ?? {}).cast<String, dynamic>();
    await _loadImage();
    _snapshotKey = snapshotKey;
    _lastBadge = badge;
    if (!_disposed) notifyListeners();
  }

  Future<void> _loadImage() async {
    final item = current;
    final kind = !original && item?['has_result'] == true
        ? 'result'
        : 'original';
    final key =
        '$selected/$kind/${item?['job_id']}/${item?['status'] == 'done'}';
    if (key == _imageKey) return;
    _imageKey = key;
    pixels = null;
    if (item == null || item['source_path'] == null) return;
    if (const [
      '[filename]',
      '(filename)',
      '{filename}',
    ].contains(item['name'])) {
      error =
          'FastStone не подставил путь к файлу. '
          'Укажите параметры внешней программы: --quick (filename)';
      return;
    }
    try {
      final data = await api.getBytes('/api/quick/image/$selected/$kind');
      if (!_disposed && _imageKey == key) pixels = data;
    } catch (e) {
      if (!_disposed && _imageKey == key) {
        final reason = '${item['error'] ?? ''}';
        error = reason.isNotEmpty
            ? reason
            : e is ApiException
            ? apiErrorMessage(e)
            : '$e';
      }
    }
  }

  Future<void> toggle() async {
    original = !original;
    await _loadImage();
    if (!_disposed) notifyListeners();
  }

  /// Всегда копируем полный результат, независимо от масштаба и показа оригинала.
  Future<void> copyTranslation(String itemId) async {
    final bytes = await api.getBytes('/api/quick/image/$itemId/result');
    final codec = await ui.instantiateImageCodec(bytes);
    try {
      final frame = await codec.getNextFrame();
      try {
        final rgba = await frame.image.toByteData(
          format: ui.ImageByteFormat.rawRgba,
        );
        if (rgba == null) throw StateError('Не удалось прочитать изображение');
        await hostWindows.invokeMethod<void>('copyImage', {
          'width': frame.image.width,
          'height': frame.image.height,
          'rgba': rgba.buffer.asUint8List(
            rgba.offsetInBytes,
            rgba.lengthInBytes,
          ),
        });
      } finally {
        frame.image.dispose();
      }
    } finally {
      codec.dispose();
    }
  }

  Future<void> move(int direction) async {
    final index = items.indexWhere((x) => x['id'] == selected);
    final next = index + direction;
    if (next < 0 || next >= items.length) return;
    await action('select', {'id': items[next]['id']});
  }

  void showError(Object value) {
    if (_disposed) return;
    error = value is ApiException ? apiErrorMessage(value) : '$value';
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    api.close();
    viewTransform.dispose();
    super.dispose();
  }
}

class QuickApp extends StatelessWidget {
  const QuickApp({
    super.key,
    required this.controller,
    required this.onOpenEditor,
  });
  final QuickController controller;
  final Future<void> Function(Map<String, dynamic>) onOpenEditor;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: ThemeData.dark(),
    home: QuickSurface(controller: controller, onOpenEditor: onOpenEditor),
  );
}

/// Только изображение, бейдж и контекстное меню; оболочка редактора не строится.
class QuickSurface extends StatelessWidget {
  const QuickSurface({
    super.key,
    required this.controller,
    required this.onOpenEditor,
  });
  final QuickController controller;
  final Future<void> Function(Map<String, dynamic>) onOpenEditor;

  Future<void> _guard(Future<void> Function() operation) async {
    try {
      await operation();
    } catch (e) {
      controller.showError(e);
    }
  }

  Future<void> _menu(BuildContext context, Offset point) async {
    final item = controller.current;
    final busy = item?['status'] == 'queued' || item?['status'] == 'running';
    final hasResult = item?['has_result'] == true;
    final index = controller.items.indexWhere((x) => x['id'] == item?['id']);
    final overlay =
        Overlay.of(context).context.findRenderObject()! as RenderBox;
    final action = await showMenu<String>(
      context: context,
      position: RelativeRect.fromRect(
        Rect.fromLTWH(point.dx, point.dy, 0, 0),
        Offset.zero & overlay.size,
      ),
      items: [
        if (hasResult)
          const PopupMenuItem(value: 'copy', child: Text('Копировать')),
        if (hasResult)
          PopupMenuItem(
            value: 'toggle',
            child: Text(
              controller.original ? 'Показать перевод' : 'Показать оригинал',
            ),
          ),
        if (hasResult)
          const PopupMenuItem(value: 'save', child: Text('Сохранить как…')),
        if (busy) const PopupMenuItem(value: 'cancel', child: Text('Отменить')),
        if (item != null && !busy)
          const PopupMenuItem(value: 'retry', child: Text('Повторить')),
        if (item != null)
          const PopupMenuItem(value: 'report', child: Text('Багрепорт…')),
        if (item != null && !busy)
          const PopupMenuItem(
            value: 'editor',
            child: Text('Открыть в редакторе'),
          ),
        if (item != null)
          const PopupMenuItem(
            value: 'remove',
            child: Text('Убрать из очереди'),
          ),
        if (index > 0)
          const PopupMenuItem(value: 'previous', child: Text('Предыдущее')),
        if (item != null && index + 1 < controller.items.length)
          const PopupMenuItem(value: 'next', child: Text('Следующее')),
        const PopupMenuItem(value: 'server', child: Text('Сервер…')),
      ],
    );
    if (action == null || !context.mounted) return;
    if (action == 'server') {
      await _server(context);
      return;
    }
    if (item == null) return;
    // Действие относится к кадру, на котором было открыто меню.
    if (controller.selected != item['id']) {
      await controller.action('select', {'id': item['id']});
    }
    switch (action) {
      case 'copy':
        await controller.copyTranslation('${item['id']}');
      case 'toggle':
        await controller.toggle();
      case 'save':
        if (context.mounted) await _save(context, item);
      case 'report':
        if (context.mounted) await _report(context, '${item['id']}');
      case 'editor':
        await onOpenEditor({'quick_item_id': item['id']});
      case 'previous':
        await controller.move(-1);
      case 'next':
        await controller.move(1);
      default:
        await controller.action(action, {'id': item['id']});
    }
  }

  Future<void> _server(BuildContext context) async {
    final url = TextEditingController(
      text: '${controller.server['url'] ?? 'http://192.168.88.41:8765'}',
    );
    final code = TextEditingController();
    final payload = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Сервер перевода'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: url,
                decoration: const InputDecoration(labelText: 'Адрес LAN API'),
              ),
              TextField(
                controller: code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: 'Код сопряжения',
                  hintText: '6 цифр с сервера',
                ),
              ),
              Text(
                controller.server['paired'] == true
                    ? 'Сопряжение сохранено. Для смены сервера нужен новый код.'
                    : 'Получите код на сервере, как для расширения браузера.',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, {
              'url': url.text.trim(),
              'code': code.text.trim(),
            }),
            child: const Text('Подключить'),
          ),
        ],
      ),
    );
    Future<void>.delayed(const Duration(seconds: 1), () {
      url.dispose();
      code.dispose();
    });
    if (payload != null) await controller.action('server', payload);
  }

  Future<bool> _replace(BuildContext context) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Заменить существующий файл?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Заменить'),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _save(BuildContext context, Map<String, dynamic> item) async {
    final name = '${item['name'] ?? 'image'}'.replaceFirst(
      RegExp(r'\.[^.]+$'),
      '',
    );
    final location = await getSaveLocation(
      suggestedName: '${name}_${item['target_lang'] ?? 'ru'}.png',
      acceptedTypeGroups: [
        const XTypeGroup(label: 'PNG', extensions: ['png']),
      ],
    );
    if (location == null || !context.mounted) return;
    var overwrite = false;
    if (await File(location.path).exists()) {
      if (!context.mounted) return;
      overwrite = await _replace(context);
      if (!overwrite) return;
    }
    try {
      await controller.action('save', {
        'id': item['id'],
        'path': location.path,
        'overwrite': overwrite,
      });
    } on ApiException catch (e) {
      if (e.statusCode != 409 || !context.mounted || !await _replace(context)) {
        rethrow;
      }
      await controller.action('save', {
        'id': item['id'],
        'path': location.path,
        'overwrite': true,
      });
    }
  }

  Future<void> _report(BuildContext context, String itemId) async {
    final text = TextEditingController();
    final note = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('Что не так?'),
          content: TextField(
            controller: text,
            autofocus: true,
            maxLength: 4000,
            minLines: 3,
            maxLines: 6,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(hintText: 'Опишите проблему'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Отмена'),
            ),
            TextButton(
              onPressed: text.text.trim().isEmpty
                  ? null
                  : () => Navigator.pop(context, text.text.trim()),
              child: const Text('Сохранить отчёт'),
            ),
          ],
        ),
      ),
    );
    // Контроллер поля нужен до завершения анимации закрытия диалога.
    Future<void>.delayed(const Duration(seconds: 1), text.dispose);
    if (note == null) return;
    final result = await controller.action('bug-report', {
      'id': itemId,
      'note': note,
    });
    await platform.openFolder('${result['path']}');
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final item = controller.current;
      final badge = controller.badge;
      final message = controller.error.isNotEmpty
          ? controller.error
          : '${item?['error'] ?? ''}';
      final warning = (item?['warnings'] as List? ?? []).join('\n');
      return Scaffold(
        backgroundColor: const Color(0xFF151515),
        body: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onSecondaryTapUp: (details) =>
              _guard(() => _menu(context, details.globalPosition)),
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (controller.pixels != null)
                QuickImageView(
                  key: ValueKey(controller.selected),
                  pixels: controller.pixels!,
                  transformationController: controller.viewTransform,
                ),
              if (item == null)
                const Center(child: Text('Отправьте изображение из FastStone')),
              if (message.isNotEmpty)
                Center(
                  child: Container(
                    color: Colors.black87,
                    padding: const EdgeInsets.all(16),
                    child: Text(message, textAlign: TextAlign.center),
                  ),
                ),
              if (warning.isNotEmpty && badge == '✓')
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Container(
                    color: Colors.black87,
                    padding: const EdgeInsets.all(12),
                    child: Text(warning),
                  ),
                ),
              if (badge.isNotEmpty)
                Positioned(
                  top: 12,
                  right: 12,
                  child: Tooltip(
                    message: message.isNotEmpty
                        ? message
                        : warning.isNotEmpty
                        ? warning
                        : controller.stage,
                    child: Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: Colors.black87,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (item?['status'] == 'running')
                            Padding(
                              padding: const EdgeInsets.only(right: 8),
                              child: SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  value:
                                      ((item?['progress'] as num? ?? 0) / 100)
                                          .clamp(0, 1),
                                  strokeWidth: 2,
                                ),
                              ),
                            ),
                          Text(badge),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      );
    },
  );
}
