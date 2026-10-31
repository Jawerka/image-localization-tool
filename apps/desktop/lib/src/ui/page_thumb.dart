import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../state/workspace_state.dart';
import 'theme.dart';

/// Миниатюра страницы для левого рельса (макет `.prow__thumb`).
///
/// Байты отдаёт `WorkspaceState.loadThumbnail` (серверный `thumb.jpg`), декод —
/// один раз на ключ `id|status` (после прогона сервер перезаписывает `thumb`,
/// поэтому статус в ключе). Кэш LRU ~64: картинки небольшие, освобождаются
/// сборщиком после вытеснения; нет изображения — плейсхолдер.
class PageThumb extends StatefulWidget {
  const PageThumb({
    super.key,
    required this.workspace,
    required this.pageId,
    required this.status,
  });

  final WorkspaceState workspace;
  final String pageId;
  final String status;

  @override
  State<PageThumb> createState() => _PageThumbState();
}

class _PageThumbState extends State<PageThumb> {
  static const _cacheLimit = 64;
  static final Map<String, ui.Image> _cache = {};
  static final List<String> _order = [];

  ui.Image? _image;
  bool _loading = false;

  String get _key => '${widget.pageId}|${widget.status}';

  @override
  void initState() {
    super.initState();
    _resolve();
  }

  @override
  void didUpdateWidget(covariant PageThumb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.pageId != widget.pageId ||
        oldWidget.status != widget.status) {
      _resolve();
    }
  }

  /// Отдать картинку из кэша или запросить и декодировать (targetWidth 2×
  /// экранной ширины 55 — ретина хватает без заметной памяти).
  Future<void> _resolve() async {
    final key = _key;
    final cached = _cache[key];
    if (cached != null) {
      _touch(key);
      if (mounted) setState(() => _image = cached);
      return;
    }
    if (_loading) return;
    _loading = true;
    final bytes = await widget.workspace.loadThumbnail(widget.pageId);
    ui.Image? decoded;
    if (bytes != null && bytes.isNotEmpty) {
      try {
        final codec = await ui.instantiateImageCodec(bytes, targetWidth: 110);
        final frame = await codec.getNextFrame();
        decoded = frame.image;
      } catch (_) {
        decoded = null;
      }
    }
    _loading = false;
    if (!mounted || key != _key) return;
    if (decoded != null) {
      _cache[key] = decoded;
      _touch(key);
      while (_order.length > _cacheLimit) {
        _cache.remove(_order.removeAt(0));
      }
    }
    setState(() => _image = decoded);
  }

  void _touch(String key) {
    _order.remove(key);
    _order.add(key);
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final image = _image;
    return Container(
      key: Key('pages-thumb-${widget.pageId}'),
      width: 55,
      height: 75,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: palette.surface2,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: palette.line),
      ),
      child: image == null
          ? Center(
              child: Icon(
                Icons.image_outlined,
                size: 16,
                color: palette.textMuted.withValues(alpha: 0.6),
              ),
            )
          : RawImage(image: image, fit: BoxFit.cover),
    );
  }
}
