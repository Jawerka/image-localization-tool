import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../api/ilt_api.dart';
import '../sidecar/handshake.dart';
import 'quick_app.dart';
import 'quick_image_view.dart';
import 'window_bridge.dart';

/// Оригинал виден до запуска Python; после handshake включается та же quick-сессия.
class QuickStartup extends StatefulWidget {
  const QuickStartup({
    super.key,
    required this.onReady,
    required this.onOpenEditor,
    this.controllerFactory,
    this.loadPreview,
  });

  final void Function(QuickController) onReady;
  final Future<void> Function(Map<String, dynamic>) onOpenEditor;
  final QuickController Function(ApiReady)? controllerFactory;
  final Future<Uint8List> Function(String)? loadPreview;

  @override
  State<QuickStartup> createState() => _QuickStartupState();
}

class _QuickStartupState extends State<QuickStartup> {
  QuickController? _controller;
  Uint8List? _preview;
  String _path = '';
  String _error = '';
  final _viewTransform = TransformationController();

  @override
  void initState() {
    super.initState();
    unawaited(_connect());
  }

  Future<void> _previewPath(String path) async {
    if (!RegExp(r'\.(png|jpe?g|bmp)$', caseSensitive: false).hasMatch(path)) {
      return;
    }
    try {
      if (widget.loadPreview == null &&
          await File(path).length() > 64 * 1024 * 1024) {
        return;
      }
      final pixels =
          await (widget.loadPreview?.call(path) ?? File(path).readAsBytes());
      if (mounted && path == _path) setState(() => _preview = pixels);
    } on FileSystemException {
      // Конкретную причину файла покажет обычная quick-сессия.
    }
  }

  Future<void> _connect() async {
    final deadline = DateTime.now().add(const Duration(seconds: 30));
    try {
      while (mounted && DateTime.now().isBefore(deadline)) {
        final data = await hostWindows.invokeMapMethod<String, dynamic>(
          'getApi',
        );
        if (!mounted) return;
        final ready = data == null ? null : ApiReady.tryParse(jsonEncode(data));
        if (ready != null) {
          final controller =
              widget.controllerFactory?.call(ready) ??
              QuickController(IltApi(ready: ready));
          // Сначала получаем кадр, чтобы подключение не мигало пустым фоном.
          await controller.refresh();
          if (!mounted) {
            controller.dispose();
            return;
          }
          widget.onReady(controller);
          controller.viewTransform.value = _viewTransform.value.clone();
          setState(() {
            _controller = controller;
            _preview = null;
          });
          controller.start();
          return;
        }
        final paths = data?['paths'];
        if (paths is List &&
            paths.isNotEmpty &&
            paths.last is String &&
            paths.last != _path) {
          _path = paths.last as String;
          unawaited(_previewPath(_path));
        }
        final failure = data?['error'];
        if (failure is String && failure.isNotEmpty) {
          setState(() => _error = failure);
          return;
        }
        await Future<void>.delayed(const Duration(milliseconds: 25));
      }
      if (mounted) {
        setState(
          () => _error =
              'Не удалось запустить служебный процесс. Закройте окно и повторите запуск.',
        );
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = 'Не удалось запустить быстрое окно: $error');
      }
    }
  }

  void _previewShown() {
    // Необязательная трассировка замеров; обычный запуск не пишет этот файл.
    final path = Platform.environment['ILT_STARTUP_TRACE'];
    if (path == null || path.isEmpty) return;
    try {
      File(path).writeAsStringSync(
        '${DateTime.now().microsecondsSinceEpoch}\n',
        mode: FileMode.append,
      );
    } on FileSystemException {
      // Замер не должен влиять на работу окна.
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    _viewTransform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    if (controller != null) {
      return QuickApp(
        controller: controller,
        onOpenEditor: widget.onOpenEditor,
      );
    }
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(),
      home: Scaffold(
        backgroundColor: const Color(0xFF151515),
        body: Stack(
          fit: StackFit.expand,
          children: [
            if (_preview != null)
              QuickImageView(
                pixels: _preview!,
                onFirstFrame: _previewShown,
                transformationController: _viewTransform,
              ),
            if (_error.isNotEmpty)
              Center(
                child: Container(
                  color: Colors.black87,
                  padding: const EdgeInsets.all(16),
                  child: Text(_error),
                ),
              ),
            if (_path.isEmpty && _error.isEmpty)
              const Center(child: Text('Отправьте изображение из FastStone')),
            if (_error.isEmpty && _path.isNotEmpty)
              Positioned(
                top: 12,
                right: 12,
                child: Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.black87,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text('В очереди 1'),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
