import 'dart:async';
import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../api/errors.dart';
import '../api/ilt_api.dart';
import '../model/page_document.dart';
import '../model/view_transform.dart';

/// Снимок документа вместе с оценкой его размера в JSON-байтах.
class _HistoryEntry {
  _HistoryEntry(this.snapshot, this.bytes);

  final Map<String, dynamic> snapshot;
  final int bytes;
}

/// История правок одной страницы (снимки документа).
class _PageHistory {
  final List<_HistoryEntry> past = [];
  final List<_HistoryEntry> future = [];
  int pastBytes = 0;
  int futureBytes = 0;
  static const limit = 1000;
  static const maxBytes = 256 * 1024 * 1024;

  void addPast(Map<String, dynamic> snapshot, int bytes) {
    past.add(_HistoryEntry(snapshot, bytes));
    pastBytes += bytes;
    _trim(past, pastBytes, (value) => pastBytes = value);
  }

  void addFuture(Map<String, dynamic> snapshot, int bytes) {
    future.add(_HistoryEntry(snapshot, bytes));
    futureBytes += bytes;
    _trim(future, futureBytes, (value) => futureBytes = value);
  }

  _HistoryEntry popPast() {
    final entry = past.removeLast();
    pastBytes -= entry.bytes;
    return entry;
  }

  _HistoryEntry popFuture() {
    final entry = future.removeLast();
    futureBytes -= entry.bytes;
    return entry;
  }

  void clearFuture() {
    future.clear();
    futureBytes = 0;
  }

  static void _trim(
    List<_HistoryEntry> entries,
    int bytes,
    void Function(int) setBytes,
  ) {
    var total = bytes;
    while (entries.length > limit || (total > maxBytes && entries.length > 1)) {
      total -= entries.removeAt(0).bytes;
    }
    setBytes(total);
  }
}

/// Состояние просмотрщика: документ активной страницы, правки, инструменты.
///
/// Зеркало `web/js/state.js` + `web/js/viewer.js` для канваса: черновик правок
/// до «Готово», undo/redo по одной правке, отложенное сохранение с ретраем при
/// конфликте версий, кэш изображений страницы.
class ViewerState extends ChangeNotifier {
  ViewerState();

  IltApi? _api;
  String? _pageId;
  PageDocument? _document;
  String? _selectedRegionId;
  String? _textMoveRegionId;

  String _tool = 'select';
  String _view = 'result';
  double _curtain = 0.46;
  bool _showBoxes = true;
  bool _showMask = true;
  double _brushSize = 12;
  double _fillTolerance = 20;

  /// Уведомить о смене слоёв для сохранения в настройках.
  void Function(bool boxes, bool mask)? onLayersChanged;

  ui.Size _imageSize = ui.Size.zero;
  bool _loading = false;
  String? _errorText;
  bool _disposed = false;

  final Map<String, ui.Image> _images = {};
  final Set<String> _loadingImages = {};
  final List<String> _imageOrder = [];
  static const _imageCacheLimit = 16;
  static const _imageByteLimit = 128 * 1024 * 1024;
  static const _fillPreviewLimit = 32;

  final Map<String, FillPreview> _fillPreviews = {};
  final Set<String> _fillPending = {};

  final Map<String, Map<String, dynamic>> _pendingBody = {};
  final Map<String, int> _acked = {};

  /// Число штрихов, уже запечённых в маску версии (`pageId|version`).
  final Map<String, int> _strokeCounts = {};
  final Map<String, _PageHistory> _histories = {};
  String _coalesceKey = '';
  String _deferredBaselineKey = '';
  bool _deferredApply = false;
  Timer? _saveTimer;
  String _timerPage = '';
  String _inflight = '';
  String _queuedPage = '';
  int _loadToken = 0;

  Future<void> Function()? _pendingLeave;
  Completer<bool>? _leaveCompleter;

  // ---- инспектор (024): шрифты, стили, действия, предпросмотр ---------------

  int _fontMin = 10;
  int _fontMax = 128;
  List<Map<String, dynamic>> _fonts = const [];
  bool _fontsRequested = false;
  final Map<String, String> _fontFamilies = {};

  List<Map<String, dynamic>> _styleLibrary = const [];
  String _styleProjectId = '';
  bool _styleLibraryLoaded = false;
  Map<String, dynamic>? _styleClipboard;

  String _pendingActionRegionId = '';
  String _pendingAction = '';

  String _sfxRegionId = '';
  String _sfxStatus = 'idle';
  String _sfxMessage = '';

  ui.Image? _stylePreviewImage;
  Offset _stylePreviewOffset = Offset.zero;
  String _stylePreviewStatus = 'idle';
  String _stylePreviewMessage = '';
  Timer? _previewTimer;
  int _previewToken = 0;
  String _previewKey = '';

  final Map<String, Future<ui.Image?>> _imageLoads = {};

  ui.Image? _basePageImage;
  ui.Image? _textLayerImage;
  ui.Image? _overlayLayerImage;
  Offset _textLayerOrigin = Offset.zero;
  Offset _textLayerAnchor = Offset.zero;
  Offset _overlayLayerOrigin = Offset.zero;
  String _localLayoutKey = '';
  String _localPreviewRegionId = '';
  bool _localPreviewRequested = false;

  int _deferredStartDepth = -1;
  bool _applying = false;
  bool _awaitingBake = false;
  bool _bakeFailed = false;
  String _applyError = '';
  String _failedSavePage = '';
  String _lastSavePlan = '';

  // ---- геттеры -------------------------------------------------------------

  String? get pageId => _pageId;
  PageDocument? get document => _document;
  String? get selectedRegionId => _selectedRegionId;
  bool isTextMoveActive(String regionId) => _textMoveRegionId == regionId;
  String get tool => _tool;
  String get view => _view;
  double get curtain => _curtain;
  bool get showBoxes => _showBoxes;
  bool get showMask => _showMask;
  double get brushSize => _brushSize;
  double get fillTolerance => _fillTolerance;
  Map<String, FillPreview> get fillPreviews => _fillPreviews;
  ui.Size get imageSize => _imageSize;
  bool get loading => _loading;
  String? get errorText => _errorText;

  /// Черновик правок ждёт «Готово».
  bool get hasDeferredDraft => _deferredApply;
  bool get isApplying => _applying;
  String get applyError => _applyError;

  /// Смещение перетаскиваемой пилюли «N правок» (в пределах сессии).
  Offset _pillOffset = Offset.zero;
  Offset get pillOffset => _pillOffset;

  void dragPill(Offset delta) {
    _pillOffset += delta;
    _notify();
  }

  /// Число неприменённых правок (для пилюли): только записи черновика.
  int get editCount {
    if (!_deferredApply) return 0;
    final history = _historyFor(_pageId);
    final depth = _deferredStartDepth < 0 ? 0 : _deferredStartDepth;
    final count = history.past.length - depth;
    return count < 1 ? 1 : count;
  }

  bool get canUndo => _historyFor(_pageId).past.isNotEmpty;
  bool get canRedo => _historyFor(_pageId).future.isNotEmpty;

  /// Есть незавершённый запрос на уход со страницы (диалог применить/отменить).
  bool get leavePromptVisible => _pendingLeave != null;

  ui.Image? imageFor(String kind) {
    final pageId = _pageId;
    if (pageId == null) return null;
    final version = _document?.version ?? 0;
    final exact = _images['$pageId|$kind|$version'];
    if (exact != null) return exact;
    // Пока новая версия не декодирована — держим предыдущую картинку.
    final prefix = '$pageId|$kind|';
    for (final key in _imageOrder.reversed) {
      if (key.startsWith(prefix)) {
        return _images[key];
      }
    }
    return null;
  }

  /// Изображение именно текущей версии уже декодировано.
  bool hasFreshImage(String kind) {
    final pageId = _pageId;
    final document = _document;
    if (pageId == null || document == null) return false;
    return _images.containsKey('$pageId|$kind|${document.version}');
  }

  /// Версия картинки, которую реально показывает [imageFor] (с fallback).
  int? _versionForImage(String kind) {
    final pageId = _pageId;
    if (pageId == null) return null;
    final version = _document?.version ?? 0;
    if (_images.containsKey('$pageId|$kind|$version')) return version;
    final prefix = '$pageId|$kind|';
    for (final key in _imageOrder.reversed) {
      if (key.startsWith(prefix)) {
        return int.tryParse(key.substring(prefix.length));
      }
    }
    return null;
  }

  /// Сколько штрихов уже входит в показанную маску: цветными остаются
  /// только более новые ручные назначения.
  int get bakedStrokeCount {
    final pageId = _pageId;
    final document = _document;
    if (pageId == null || document == null) return 0;
    final version = _versionForImage('mask') ?? document.version;
    return _strokeCounts['$pageId|$version'] ?? document.strokes.length;
  }

  _PageHistory _historyFor(String? pageId) {
    final id = pageId ?? '';
    return _histories.putIfAbsent(id, _PageHistory.new);
  }

  // ---- привязка ------------------------------------------------------------

  void bind(IltApi api) {
    _api = api;
    _errorText = null;
    notifyListeners();
  }

  void detach() {
    _saveTimer?.cancel();
    _saveTimer = null;
    _timerPage = '';
    _inflight = '';
    _queuedPage = '';
    _pendingBody.clear();
    _acked.clear();
    _strokeCounts.clear();
    _histories.clear();
    _coalesceKey = '';
    _deferredBaselineKey = '';
    _deferredApply = false;
    _deferredStartDepth = -1;
    _awaitingBake = false;
    _applyError = '';
    _clearPreview();
    _styleLibrary = const [];
    _styleProjectId = '';
    _styleLibraryLoaded = false;
    _styleClipboard = null;
    _pendingAction = '';
    _pendingActionRegionId = '';
    _sfxRegionId = '';
    _sfxStatus = 'idle';
    _sfxMessage = '';
    _disposeImages();
    _pageId = null;
    _document = null;
    _selectedRegionId = null;
    _textMoveRegionId = null;
    _imageSize = ui.Size.zero;
    _loading = false;
    _cancelLeave(false);
    notifyListeners();
  }

  void clearError() {
    if (_errorText == null) return;
    _errorText = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _previewTimer?.cancel();
    _saveTimer?.cancel();
    _saveTimer = null;
    _timerPage = '';
    _stylePreviewImage?.dispose();
    _stylePreviewImage = null;
    _disposeImages();
    super.dispose();
  }

  void _notify() {
    if (_disposed) return;
    notifyListeners();
  }

  void _disposeImages() {
    for (final image in _images.values) {
      image.dispose();
    }
    _images.clear();
    _loadingImages.clear();
    _imageLoads.clear();
    _imageOrder.clear();
    _disposeFillPreviews();
  }

  void _disposeFillPreviews() {
    for (final preview in _fillPreviews.values) {
      preview.image.dispose();
    }
    _fillPreviews.clear();
    _fillPending.clear();
  }

  // ---- загрузка страницы ---------------------------------------------------

  /// Открыть страницу (или закрыть при null). Черновик прошлой страницы
  /// отбрасывается — страж ухода вызывается до вызова (зеркало веба).
  Future<void> openPage(String? id) async {
    final next = id == null || id.isEmpty ? null : id;
    if (next == _pageId && next == null) return;
    _loadToken++;
    _strokeCounts.clear();
    final previous = _pageId;
    if (previous != null && previous != next) {
      _pendingBody.remove(previous);
      _deferredApply = false;
      _deferredBaselineKey = '';
      _deferredStartDepth = -1;
      _awaitingBake = false;
      _bakeFailed = false;
      _applyError = '';
      _coalesceKey = '';
      if (_timerPage == previous) {
        _saveTimer?.cancel();
        _saveTimer = null;
        _timerPage = '';
      }
      _histories.remove(previous);
    }
    _clearPreview();
    if (previous != next) _disposeFillPreviews();
    _pendingAction = '';
    _pendingActionRegionId = '';
    _sfxRegionId = '';
    _sfxStatus = 'idle';
    _sfxMessage = '';
    _pageId = next;
    _document = null;
    _selectedRegionId = null;
    _textMoveRegionId = null;
    _imageSize = ui.Size.zero;
    _errorText = null;
    _loading = next != null;
    if (next != null && previous != next) session.homeForPage();
    _notify();
    if (next == null) return;
    await _reloadDetail(next);
  }

  /// Перечитать активную страницу, если нет незавершённых правок.
  Future<void> reloadIfClean(String pageId) async {
    if (pageId != _pageId) return;
    if (isDirty(pageId)) return;
    await _reloadDetail(pageId);
  }

  /// Перечитать документ страницы (принудительно — затерев локальные правки).
  Future<bool> reloadDetail(String pageId, {bool force = false}) =>
      _reloadDetail(pageId, force: force);

  Future<bool> _reloadDetail(
    String pageId, {
    bool force = false,
    bool keepPreview = false,
  }) async {
    final api = _api;
    if (api == null) return false;
    final token = ++_loadToken;
    try {
      final data = await api.getJson('/api/pages/$pageId');
      if (token != _loadToken || pageId != _pageId) return false;
      _applyDetail(pageId, data, force: force, keepPreview: keepPreview);
      return true;
    } on ApiException catch (error) {
      if (token != _loadToken) return false;
      _errorText = apiErrorMessage(error);
      return false;
    } finally {
      if (token == _loadToken && pageId == _pageId) {
        _loading = false;
        _notify();
      }
    }
  }

  void _applyDetail(
    String pageId,
    Map<String, dynamic> data, {
    bool keepLocal = false,
    bool force = false,
    bool keepPreview = false,
  }) {
    final root = data;
    final page = root['page'] is Map ? root['page'] as Map : root;
    final documentRaw = root['document'] ?? page['document'];
    if (documentRaw is! Map) return;
    final document = PageDocument.fromJson(documentRaw.cast<String, dynamic>());
    _acked[pageId] = document.version;
    _strokeCounts['$pageId|${document.version}'] = document.strokes.length;
    final dirty = isDirty(pageId) && pageId == _pageId && _document != null;
    if ((keepLocal || dirty) && !force) {
      _document?.version = document.version;
      _notify();
      return;
    }
    if (force) {
      _pendingBody.remove(pageId);
      if (_timerPage == pageId) {
        _saveTimer?.cancel();
        _saveTimer = null;
        _timerPage = '';
      }
      _coalesceKey = '';
      _deferredBaselineKey = '';
      _deferredApply = false;
      _deferredStartDepth = -1;
    }
    _document = document;
    _localPreviewRequested = false;
    if (keepPreview) {
      _previewTimer?.cancel();
      _previewTimer = null;
      _previewToken++;
    } else {
      _clearPreview();
    }
    _pruneSelection();
    ensureImages();
    _ensureFillPreviews();
    _notify();
  }

  void _pruneSelection() {
    if (_selectedRegionId != null &&
        _document?.findRegion(_selectedRegionId) == null) {
      _selectedRegionId = null;
    }
  }

  // ---- изображения ---------------------------------------------------------

  /// Запросить картинки, нужные текущему виду.
  void ensureImages() {
    final pageId = _pageId;
    final document = _document;
    if (pageId == null || document == null) return;
    final version = document.version;
    final kinds = <String>{
      // Оригинал всегда нужен как источник размера листа, пока result
      // ещё не готов или не декодирован.
      'original',
      if (_view == 'clean') 'clean' else if (_view != 'original') 'result',
      if (_showMask) 'mask',
    };
    for (final kind in kinds) {
      _requestImage(pageId, kind, version);
    }
  }

  void _requestImage(String pageId, String kind, int version) {
    unawaited(_loadImage(pageId, kind, version));
  }

  /// Дождаться декодированной картинки текущей ревизии (для атомарного Done).
  Future<bool> _awaitCurrentImage(String pageId) async {
    final document = _document;
    if (document == null || pageId != _pageId) return false;
    final kind = _view == 'clean'
        ? 'clean'
        : (_view == 'original' ? 'original' : 'result');
    final image = await _loadImage(pageId, kind, document.version);
    return image != null && !_disposed && pageId == _pageId;
  }

  Future<ui.Image?> _loadImage(String pageId, String kind, int version) {
    final key = '$pageId|$kind|$version';
    final cached = _images[key];
    if (cached != null) return Future<ui.Image?>.value(cached);
    final loading = _imageLoads[key];
    if (loading != null) return loading;
    final api = _api;
    if (api == null) return Future<ui.Image?>.value();
    late final Future<ui.Image?> future;
    future = () async {
      _loadingImages.add(key);
      try {
        final bytes = await api.getBytes(
          '/api/pages/$pageId/image/$kind?v=$version',
        );
        final codec = await ui.instantiateImageCodec(bytes);
        late final ui.FrameInfo frame;
        try {
          frame = await codec.getNextFrame();
        } finally {
          codec.dispose();
        }
        if (_disposed) {
          frame.image.dispose();
          return null;
        }
        _images[key] = frame.image;
        _imageOrder.remove(key);
        _imageOrder.add(key);
        _evictImages();
        _notify();
        return frame.image;
      } on ApiException {
        // нет mask/result — нормально: слой просто пуст
        return null;
      } catch (_) {
        // декод не удался — слой пуст
        return null;
      } finally {
        _loadingImages.remove(key);
        _imageLoads.remove(key);
      }
    }();
    _imageLoads[key] = future;
    return future;
  }

  void _evictImages() {
    var total = 0;
    for (final key in _imageOrder) {
      final image = _images[key];
      if (image != null) total += image.width * image.height * 4;
    }
    while (_imageOrder.length > _imageCacheLimit ||
        (total > _imageByteLimit && _imageOrder.length > 1)) {
      final oldest = _imageOrder.removeAt(0);
      final image = _images.remove(oldest);
      if (image != null) {
        total -= image.width * image.height * 4;
        image.dispose();
      }
    }
  }

  void _reportImageSize(ui.Image image) {
    final size = ui.Size(image.width.toDouble(), image.height.toDouble());
    if (_imageSize != size) {
      _imageSize = size;
    }
  }

  /// Вызывается канвасом после декода базовой картинки (размер листа).
  void noteDisplayedImage(ui.Image? image) {
    if (image == null) return;
    _reportImageSize(image);
  }

  // ---- инструменты и вид ---------------------------------------------------

  void setTool(String tool) {
    if (_tool == tool) return;
    _tool = tool;
    if (tool != 'polyline') session.clearLasso();
    _notify();
  }

  void setView(String view) {
    if (_view == view) return;
    _view = view;
    ensureImages();
    _notify();
  }

  void setShowBoxes(bool value) {
    if (_showBoxes == value) return;
    _showBoxes = value;
    if (!value) _selectedRegionId = null;
    _notify();
    onLayersChanged?.call(_showBoxes, _showMask);
  }

  void toggleBoxes() => setShowBoxes(!_showBoxes);

  void setShowMask(bool value) {
    if (_showMask == value) return;
    _showMask = value;
    if (value) ensureImages();
    _notify();
    onLayersChanged?.call(_showBoxes, _showMask);
  }

  void toggleMask() => setShowMask(!_showMask);

  /// Применить сохранённые значения без записи (bootstrap).
  void restoreLayers({required bool boxes, required bool mask}) {
    var changed = false;
    if (_showBoxes != boxes) {
      _showBoxes = boxes;
      changed = true;
    }
    if (_showMask != mask) {
      _showMask = mask;
      if (mask) ensureImages();
      changed = true;
    }
    if (!boxes) _selectedRegionId = null;
    if (changed) _notify();
  }

  void setBrushSize(double value) {
    final next = value.clamp(1, 64).toDouble();
    if (_brushSize == next) return;
    _brushSize = next;
    _notify();
  }

  void nudgeBrush(double delta) => setBrushSize(_brushSize + delta);

  void setFillTolerance(double value) {
    final next = value.clamp(0, 100).toDouble();
    if (_fillTolerance == next) return;
    _fillTolerance = next;
    _notify();
  }

  void nudgeFillTolerance(double delta) =>
      setFillTolerance(_fillTolerance + delta);

  void setCurtain(double value) {
    final next = value.clamp(0.02, 0.98).toDouble();
    if (_curtain == next) return;
    _curtain = next;
    _notify();
  }

  void selectRegion(String? id) {
    if (_selectedRegionId == id) return;
    _selectedRegionId = id;
    _localPreviewRequested = false;
    if (_textMoveRegionId != id) _textMoveRegionId = null;
    _schedulePreview();
    _notify();
  }

  /// Включить/выключить режим перемещения только текста (038).
  void toggleTextMove(String regionId) {
    _textMoveRegionId = _textMoveRegionId == regionId ? null : regionId;
    _notify();
  }

  /// Якорь текста: `text_position`, иначе центр баллона/рамки.
  Offset textAnchorFor(Region region) {
    final explicit = region.textPosition;
    if (explicit != null) return explicit;
    return (region.bubbleBbox ?? region.bbox).center;
  }

  /// Записать независимую позицию текста, не меняя bbox и маску.
  void setTextPosition(String regionId, Offset position) {
    editDocument(
      (document) {
        final region = document.findRegion(regionId);
        if (region == null) return;
        region.textPosition = position;
        region.edited = true;
      },
      deferApply: true,
      coalesce: 'textpos:$regionId',
    );
    _schedulePreview();
  }

  void resetTextPosition(String regionId) {
    editDocument((document) {
      final region = document.findRegion(regionId);
      if (region == null) return;
      region.textPosition = null;
      region.edited = true;
    }, deferApply: true);
    _schedulePreview();
  }

  /// Сдвиг текста стрелками: 1 px, Shift — 10 px.
  void nudgeTextPosition(String direction, {bool shift = false}) {
    final id = _selectedRegionId;
    if (id == null) return;
    final region = _document?.findRegion(id);
    if (region == null) return;
    final step = shift ? 10.0 : 1.0;
    final origin = textAnchorFor(region);
    final dx = direction == 'right'
        ? step
        : (direction == 'left' ? -step : 0.0);
    final dy = direction == 'down' ? step : (direction == 'up' ? -step : 0.0);
    setTextPosition(id, origin.translate(dx, dy));
  }

  /// Сессия жестов и матрица (живёт рядом, но уведомляет только канвас).
  late final CanvasSession session = CanvasSession(onChanged: _notify);

  // ---- правки и история ----------------------------------------------------

  bool isDirty(String pageId) =>
      _inflight == pageId ||
      _timerPage == pageId ||
      _queuedPage == pageId ||
      _pendingBody.containsKey(pageId);

  /// Правка документа (зеркало `editDocument`): история, черновик, сохранение.
  ///
  /// [deferApply] — правка ждёт «Готово»; [coalesce] склеивает серию правок
  /// одного жеста в одну запись истории; [debounceMs] — задержка сохранения.
  bool editDocument(
    void Function(PageDocument document) mutator, {
    bool deferApply = false,
    String coalesce = '',
    int debounceMs = 0,
  }) {
    if (_applying) return false;
    final pageId = _pageId;
    final current = _document;
    if (pageId == null || current == null) return false;
    final before = current.contentKey();
    final next = current.clone();
    mutator(next);
    if (next.contentKey() == before) return false;
    final history = _historyFor(pageId);
    if (coalesce.isEmpty || coalesce != _coalesceKey) {
      history.addPast(deepCopyMap(current.data), before.length);
      history.clearFuture();
      _coalesceKey = coalesce;
    }
    if (coalesce.isEmpty) _coalesceKey = '';
    _bakeFailed = false;
    final defer = deferApply || _deferredApply;
    if (defer) {
      if (_deferredBaselineKey.isEmpty) {
        _deferredBaselineKey = before;
        // индекс снимка-baseline в истории — для счётчика «N правок»
        _deferredStartDepth = history.past.length - 1;
        if (_deferredStartDepth < 0) _deferredStartDepth = 0;
      }
      _document = next;
      _deferredApply = true;
      _pendingBody[pageId] = deepCopyMap(next.data);
      _schedulePreview();
      _notify();
      return true;
    }
    _document = next;
    _deferredApply = false;
    _deferredBaselineKey = '';
    _pendingBody[pageId] = deepCopyMap(next.data);
    _scheduleSave(pageId, debounceMs);
    _schedulePreview();
    _notify();
    return true;
  }

  /// Применить накопленный черновик («Готово») и запустить перевёрстку.
  void commitDeferredEdits() {
    final pageId = _pageId;
    if (pageId == null || _document == null) return;
    if (!_deferredApply && !_pendingBody.containsKey(pageId)) return;
    _deferredBaselineKey = '';
    _deferredStartDepth = -1;
    _deferredApply = false;
    _coalesceKey = '';
    _notify();
    _scheduleSave(pageId, 0);
  }

  /// Применить черновик, дождаться сохранения и результата этой ревизии.
  ///
  /// Ошибка на любом шаге оставляет черновик и возможность повторить: тело
  /// неудачного PUT возвращается в очередь, а после успешного PUT состояние
  /// запоминается как «сохранено, результат не готов».
  Future<bool> applyDeferredEdits() async {
    final pageId = _pageId;
    final api = _api;
    if (pageId == null || api == null || _applying) return false;
    final hasDraft =
        _deferredApply || _awaitingBake || _pendingBody.containsKey(pageId);
    if (!hasDraft) return true;
    _applying = true;
    _applyError = '';
    _errorText = null;
    _failedSavePage = '';
    _lastSavePlan = '';
    _notify();
    final baseline = _deferredBaselineKey;
    final startDepth = _deferredStartDepth;
    try {
      if (!await _refreshDoneSnapshot(pageId)) return false;
      if (_disposed || _pageId != pageId) return false;
      _syncPendingSnapshots(pageId);
      final retryBody = _pendingBody.containsKey(pageId)
          ? deepCopyMap(_pendingBody[pageId]!)
          : null;
      if (_bakeFailed && retryBody == null) {
        _bakeFailed = false;
        try {
          await api.postJson('/api/pages/$pageId/rebake');
        } on ApiException catch (error) {
          _bakeFailed = true;
          _applyError = apiErrorMessage(error);
          return false;
        }
      }
      if (retryBody != null) {
        commitDeferredEdits();
        await whenSaved(pageId);
        if (_disposed || _pageId != pageId) return false;
        if (_failedSavePage == pageId) {
          _restoreApplyDraft(pageId, retryBody, baseline, startDepth);
          _applyError = (_errorText ?? '').isEmpty
              ? 'Не удалось сохранить правки'
              : _errorText!;
          return false;
        }
      }
      final plan = _lastSavePlan;
      if (retryBody != null && plan != 'typeset' && plan != 'clean') {
        if (!await _reloadDetail(pageId)) {
          _restoreApplyDraft(pageId, retryBody, baseline, startDepth);
          _applyError = (_errorText ?? '').isEmpty
              ? 'Не удалось перечитать страницу'
              : _errorText!;
          return false;
        }
        _clearPreview();
        _deferredApply = false;
        _awaitingBake = false;
        _bakeFailed = false;
        _deferredBaselineKey = '';
        _deferredStartDepth = -1;
        _notify();
        return true;
      }
      final savedVersion = _acked[pageId] ?? 0;
      final deadline = DateTime.now().add(const Duration(seconds: 30));
      while (!_disposed &&
          _pageId == pageId &&
          DateTime.now().isBefore(deadline)) {
        late final Map<String, dynamic> detail;
        try {
          detail = await api.getJson('/api/pages/$pageId');
        } on ApiException catch (error) {
          _applyError = apiErrorMessage(error);
          _awaitingBake = true;
          _deferredApply = true;
          _restoreApplyDepth(baseline, startDepth);
          return false;
        }
        if (_disposed || _pageId != pageId) return false;
        final status = '${detail['status'] ?? ''}';
        if (status == 'error') {
          final message = '${detail['error'] ?? ''}'.trim();
          _applyError = message.isEmpty
              ? 'Не удалось собрать результат'
              : message;
          _awaitingBake = true;
          _bakeFailed = true;
          _deferredApply = true;
          _restoreApplyDepth(baseline, startDepth);
          return false;
        }
        final renderVersion = (detail['render_version'] as num?)?.toInt() ?? 0;
        if (renderVersion >= savedVersion) {
          // Новый документ и картинка устанавливаются вместе: старый preview
          // остаётся до успешного декодирования результата.
          if (!await _reloadDetail(pageId, keepPreview: true)) {
            _restoreApplyDraft(pageId, retryBody, baseline, startDepth);
            _applyError = (_errorText ?? '').isEmpty
                ? 'Не удалось перечитать страницу'
                : _errorText!;
            return false;
          }
          if (!await _awaitCurrentImage(pageId)) {
            _restoreApplyDraft(pageId, retryBody, baseline, startDepth);
            _applyError = 'Не удалось загрузить результат';
            return false;
          }
          if (_disposed || _pageId != pageId) return false;
          _clearPreview();
          _deferredApply = false;
          _awaitingBake = false;
          _bakeFailed = false;
          _deferredBaselineKey = '';
          _deferredStartDepth = -1;
          _notify();
          return true;
        }
        await Future<void>.delayed(const Duration(milliseconds: 150));
      }
      _applyError = 'Результат не успел собраться';
      _awaitingBake = true;
      _deferredApply = true;
      _restoreApplyDepth(baseline, startDepth);
      return false;
    } finally {
      if (!_disposed) {
        if (_applyError.isNotEmpty) _errorText = _applyError;
        _applying = false;
        _notify();
      }
    }
  }

  void _restoreApplyDepth(String baseline, int startDepth) {
    _deferredBaselineKey = baseline;
    _deferredStartDepth = startDepth;
    _awaitingBake = true;
  }

  void _restoreApplyDraft(
    String pageId,
    Map<String, dynamic>? body,
    String baseline,
    int startDepth,
  ) {
    if (body != null) _pendingBody[pageId] = body;
    _deferredApply = true;
    _restoreApplyDepth(baseline, startDepth);
    _awaitingBake = body == null && _awaitingBake;
  }

  /// Сбросить черновик и перечитать документ с сервера.
  Future<void> discardDeferredEdits() async {
    final pageId = _pageId;
    if (pageId == null) return;
    _pendingBody.remove(pageId);
    if (_timerPage == pageId) {
      _saveTimer?.cancel();
      _saveTimer = null;
      _timerPage = '';
    }
    _coalesceKey = '';
    _deferredBaselineKey = '';
    _deferredApply = false;
    _deferredStartDepth = -1;
    _awaitingBake = false;
    _bakeFailed = false;
    _applyError = '';
    _histories.remove(pageId);
    _notify();
    await _reloadDetail(pageId);
  }

  void undo() {
    if (_applying) return;
    final pageId = _pageId;
    final current = _document;
    if (pageId == null || current == null) return;
    final history = _historyFor(pageId);
    if (history.past.isEmpty) return;
    history.addFuture(deepCopyMap(current.data), current.contentKey().length);
    _restoreHistory(pageId, history.popPast().snapshot);
  }

  void redo() {
    if (_applying) return;
    final pageId = _pageId;
    final current = _document;
    if (pageId == null || current == null) return;
    final history = _historyFor(pageId);
    if (history.future.isEmpty) return;
    history.addPast(deepCopyMap(current.data), current.contentKey().length);
    _restoreHistory(pageId, history.popFuture().snapshot);
  }

  void _restoreHistory(String pageId, Map<String, dynamic> snapshot) {
    _coalesceKey = '';
    final next = PageDocument(deepCopyMap(snapshot));
    final key = next.contentKey();
    final hadBaseline = _deferredBaselineKey.isNotEmpty;
    final pending = hadBaseline && key != _deferredBaselineKey;
    _document = next;
    _deferredApply = pending;
    _ensureFillPreviews();
    _pruneSelection();
    if (pending) {
      _pendingBody[pageId] = deepCopyMap(next.data);
      _notify();
      return;
    }
    _deferredBaselineKey = '';
    if (hadBaseline) {
      // откат к серверному baseline — черновик снят, сохранение не нужно
      _deferredStartDepth = -1;
      _pendingBody.remove(pageId);
      _notify();
      return;
    }
    _pendingBody[pageId] = deepCopyMap(next.data);
    _scheduleSave(pageId, 0);
    _notify();
  }

  // ---- сохранение ----------------------------------------------------------

  void _scheduleSave(String pageId, int delayMs) {
    if (pageId == _pageId && _document != null) {
      _pendingBody[pageId] = deepCopyMap(_document!.data);
    }
    _timerPage = pageId;
    _saveTimer?.cancel();
    _saveTimer = Timer(Duration(milliseconds: delayMs), () {
      if (_timerPage == pageId) _timerPage = '';
      unawaited(_flush(pageId));
    });
  }

  /// Дождаться сохранения (для ухода со страницы).
  Future<void> whenSaved(String? pageId) async {
    final id = pageId ?? _pageId ?? '';
    if (id.isEmpty) return;
    if (_timerPage == id) {
      _saveTimer?.cancel();
      _saveTimer = null;
      _timerPage = '';
      await _flush(id);
    }
    while (isDirty(id)) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
  }

  Future<void> _flush(String pageId) async {
    if (!_pendingBody.containsKey(pageId)) return;
    if (_inflight.isNotEmpty) {
      _queuedPage = pageId;
      return;
    }
    final api = _api;
    if (api == null) return;
    final body = _pendingBody.remove(pageId)!;
    _inflight = pageId;
    if (_queuedPage == pageId) _queuedPage = '';
    final base = _acked[pageId] ?? (body['version'] as num?)?.toInt() ?? 0;
    body['version'] = base;
    var sent = body;
    try {
      Map<String, dynamic> response;
      try {
        response = await api.putJson('/api/pages/$pageId/document', {
          'base_version': base,
          'document': body,
        });
      } on ApiException catch (error) {
        if (error.statusCode != 409) rethrow;
        final serverVersion = _conflictVersion(error);
        if (serverVersion == null) rethrow;
        _acked[pageId] = serverVersion;
        final latest = _pendingBody.remove(pageId) ?? body;
        latest['version'] = serverVersion;
        sent = latest;
        response = await api.putJson('/api/pages/$pageId/document', {
          'base_version': serverVersion,
          'document': latest,
        });
      }
      _acceptSave(pageId, response, base, _strokeCount(sent));
    } on ApiException catch (error) {
      _coalesceKey = '';
      _pendingBody.remove(pageId);
      _queuedPage = '';
      _failedSavePage = pageId;
      if (error.statusCode == 409) {
        _errorText = 'Страница изменилась, правка не сохранена';
        if (_pageId == pageId) {
          _histories.remove(pageId);
          await _reloadDetail(pageId);
        }
      } else {
        _errorText = apiErrorMessage(error);
      }
    } catch (error) {
      _coalesceKey = '';
      _pendingBody.remove(pageId);
      _queuedPage = '';
      _failedSavePage = pageId;
      _errorText = 'Не удалось сохранить правку: $error';
    } finally {
      final queued = _queuedPage;
      _inflight = '';
      _queuedPage = '';
      if (queued.isNotEmpty) {
        unawaited(_flush(queued));
      } else {
        _notify();
      }
    }
  }

  int? _conflictVersion(ApiException error) {
    final body = error.body;
    final start = body.indexOf('{');
    if (start < 0) return null;
    try {
      final decoded = jsonDecode(body.substring(start));
      if (decoded is Map) {
        final document = decoded['document'];
        if (document is Map) {
          final version = document['version'];
          if (version is num) return version.toInt();
        }
      }
    } catch (_) {
      // не разобрали — вернём null, сработает полоса конфликта
    }
    return null;
  }

  int _strokeCount(Map<String, dynamic> document) {
    final strokes = document['strokes'];
    return strokes is List ? strokes.length : 0;
  }

  void _acceptSave(
    String pageId,
    Map<String, dynamic> response,
    int fallback,
    int strokeCount,
  ) {
    final version = _readVersion(response, fallback);
    _lastSavePlan = '${response['plan'] ?? ''}';
    _acked[pageId] = version;
    _strokeCounts['$pageId|$version'] = strokeCount;
    if (_pageId == pageId &&
        _document != null &&
        !_pendingBody.containsKey(pageId)) {
      final document = response['document'];
      if (document is Map) {
        _document = PageDocument.fromJson(document.cast<String, dynamic>());
        _document!.version = version;
        _pruneSelection();
      } else {
        _document!.version = version;
      }
    }
    if (_pageId == pageId) _coalesceKey = '';
    _notify();
  }

  int _readVersion(Map<String, dynamic> response, int fallback) {
    final document = response['document'];
    if (document is Map && document['version'] is num) {
      return (document['version'] as num).toInt();
    }
    if (response['version'] is num) return (response['version'] as num).toInt();
    final page = response['page'];
    if (page is Map && page['version'] is num) {
      return (page['version'] as num).toInt();
    }
    return fallback;
  }

  // ---- команды канваса -----------------------------------------------------

  /// Завершить лассо-черновик заливкой (двойной клик/Enter). True — штрих записан.
  bool commitLassoDraft() {
    final points = session.lasso;
    if (points.length < 3) {
      session.clearLasso();
      return false;
    }
    final mode = session.lassoMode == Stroke.eraseFill
        ? Stroke.eraseFill
        : Stroke.fill;
    editDocument(
      (document) => document.addStroke(
        Stroke(
          mode: mode,
          radius: 1,
          points: [
            for (final point in points)
              Offset(point.dx.roundToDouble(), point.dy.roundToDouble()),
          ],
        ),
      ),
      deferApply: true,
    );
    session.clearLasso();
    return true;
  }

  void cancelLassoDraft() => session.clearLasso();

  /// Заливка по цвету исходной страницы (ЛКМ — добавить, ПКМ — вычесть).
  void floodFill(Offset scene, String mode) {
    final pageId = _pageId;
    final document = _document;
    if (pageId == null || document == null) return;
    final stroke = Stroke(
      mode: mode == Stroke.eraseFlood ? Stroke.eraseFlood : Stroke.flood,
      radius: 1,
      points: [Offset(scene.dx.roundToDouble(), scene.dy.roundToDouble())],
      tolerance: _fillTolerance.round(),
    );
    editDocument((doc) => doc.addStroke(stroke), deferApply: true);
    if (!_showMask) setShowMask(true);
    _requestFillPreview(pageId, stroke);
  }

  Future<void> _requestFillPreview(String pageId, Stroke stroke) async {
    final api = _api;
    final key = fillStrokeKey(stroke);
    if (api == null || key.isEmpty) return;
    if (_fillPreviews.containsKey(key) || !_fillPending.add(key)) return;
    try {
      final point = stroke.points.first;
      final response = await api.postBytes('/api/pages/$pageId/fill-preview', {
        'x': point.dx.round(),
        'y': point.dy.round(),
        'tolerance': stroke.tolerance,
        'mode': stroke.mode,
      });
      final codec = await ui.instantiateImageCodec(response.bytes);
      late final ui.FrameInfo frame;
      try {
        frame = await codec.getNextFrame();
      } finally {
        codec.dispose();
      }
      if (_disposed || pageId != _pageId) {
        frame.image.dispose();
        return;
      }
      final x = double.tryParse(response.headers['x-fill-x'] ?? '') ?? 0;
      final y = double.tryParse(response.headers['x-fill-y'] ?? '') ?? 0;
      _fillPreviews.remove(key)?.image.dispose();
      _fillPreviews[key] = FillPreview(
        image: frame.image,
        offset: Offset(x, y),
      );
      while (_fillPreviews.length > _fillPreviewLimit) {
        final oldest = _fillPreviews.keys.first;
        _fillPreviews.remove(oldest)?.image.dispose();
      }
      _notify();
    } catch (_) {
      // Превью необязательно: «Готово» всё равно пересчитает маску.
    } finally {
      _fillPending.remove(key);
    }
  }

  void _ensureFillPreviews() {
    final pageId = _pageId;
    final document = _document;
    if (pageId == null || document == null) return;
    final strokes = document.strokes;
    final baked = bakedStrokeCount.clamp(0, strokes.length).toInt();
    for (final stroke in strokes.skip(baked)) {
      if (stroke.mode == Stroke.flood || stroke.mode == Stroke.eraseFlood) {
        _requestFillPreview(pageId, stroke);
      }
    }
  }

  /// Создать регион протяжкой инструмента «Регион».
  void createRegion(Rect rect) {
    final clamped = clampBox(rect, _imageSize.width, _imageSize.height);
    var createdId = '';
    editDocument((document) {
      final id = document.nextRegionId();
      createdId = '$id';
      final region = blankRegion(id, clamped);
      region['order'] = document.regions.length;
      final list = document.data['regions'];
      if (list is List) list.add(region);
    }, deferApply: true);
    if (createdId.isEmpty) return;
    if (!_showBoxes) setShowBoxes(true);
    selectRegion(createdId);
  }

  /// Создать регион в центре видимой области (кнопка инспектора).
  void addRegionAtViewCenter() {
    final viewport = session.viewport;
    Rect box;
    if (viewport.isEmpty) {
      box = const Rect.fromLTWH(40, 40, 80, 40);
    } else {
      final transform = session.transform;
      final scale = transform.scale <= 0 ? 1.0 : transform.scale;
      final center = Offset(
        (viewport.width / 2 - transform.tx) / scale,
        (viewport.height / 2 - transform.ty) / scale,
      );
      box = Rect.fromLTWH(center.dx - 40, center.dy - 20, 80, 40);
    }
    createRegion(box);
  }

  void commitRegionRect(String regionId, Rect rect) {
    final clamped = clampBox(rect, _imageSize.width, _imageSize.height);
    editDocument((document) {
      final region = document.findRegion(regionId);
      if (region == null) return;
      region.bbox = clamped;
      region.edited = true;
    }, deferApply: true);
  }

  void commitRegionRotation(String regionId, double angle) {
    editDocument((document) {
      final region = document.findRegion(regionId);
      if (region == null) return;
      region.rotation = angle;
      region.edited = true;
    }, deferApply: true);
  }

  /// Записать точки искажения (координаты листа) в стиль региона.
  void commitWarpPoints(String regionId, List<Offset> scenePoints) {
    editDocument((document) {
      final region = document.findRegion(regionId);
      if (region == null) return;
      final bbox = region.bbox;
      final mesh = region.warp?['kind'] == 'mesh';
      final warp = <String, dynamic>{...?region.warp};
      warp['kind'] = mesh ? 'mesh' : 'perspective';
      warp[mesh ? 'mesh' : 'quad'] = [
        for (final point in scenePoints)
          [point.dx - bbox.left, point.dy - bbox.top],
      ];
      region.setWarp(warp);
      region.edited = true;
    }, deferApply: true);
  }

  /// Сбросить точку искажения к дефолту (двойной клик по точке).
  void resetWarpPoint(String regionId, int index) {
    editDocument((document) {
      final region = document.findRegion(regionId);
      if (region == null) return;
      final bbox = region.bbox;
      final mesh = region.warp?['kind'] == 'mesh';
      final defaults = mesh
          ? Region.defaultMesh(bbox.width, bbox.height)
          : Region.defaultQuad(bbox.width, bbox.height);
      if (index < 0 || index >= defaults.length) return;
      final warp = <String, dynamic>{...?region.warp};
      final key = mesh ? 'mesh' : 'quad';
      final current = _pointCopy(warp[key], defaults);
      current[index] = List<double>.of(defaults[index]);
      warp[key] = current;
      if ('${warp['kind'] ?? 'none'}' == 'none') {
        warp['kind'] = mesh ? 'mesh' : 'perspective';
      }
      region.setWarp(warp);
      region.edited = true;
    }, deferApply: true);
  }

  List<List<double>> _pointCopy(Object? raw, List<List<double>> defaults) {
    if (raw is List && raw.length == defaults.length) {
      final out = <List<double>>[];
      for (final item in raw) {
        if (item is List && item.length >= 2) {
          out.add([
            (item[0] as num?)?.toDouble() ?? 0,
            (item[1] as num?)?.toDouble() ?? 0,
          ]);
        } else {
          out.add(List<double>.of(defaults[out.length]));
        }
      }
      return out;
    }
    return [for (final point in defaults) List<double>.of(point)];
  }

  /// Сдвиг выделенного региона стрелками (Shift — 10 px, Alt — размер).
  void nudgeSelectedRegion(
    String direction, {
    bool shift = false,
    bool alt = false,
  }) {
    final id = _selectedRegionId;
    if (id == null) return;
    final step = shift ? 10.0 : 1.0;
    editDocument((document) {
      final region = document.findRegion(id);
      if (region == null) return;
      var rect = region.bbox;
      if (alt) {
        if (direction == 'right') {
          rect = Rect.fromLTWH(
            rect.left,
            rect.top,
            rect.width + step,
            rect.height,
          );
        }
        if (direction == 'left') {
          rect = Rect.fromLTWH(
            rect.left,
            rect.top,
            rect.width - step,
            rect.height,
          );
        }
        if (direction == 'down') {
          rect = Rect.fromLTWH(
            rect.left,
            rect.top,
            rect.width,
            rect.height + step,
          );
        }
        if (direction == 'up') {
          rect = Rect.fromLTWH(
            rect.left,
            rect.top,
            rect.width,
            rect.height - step,
          );
        }
      } else {
        final dx = direction == 'right'
            ? step
            : (direction == 'left' ? -step : 0.0);
        final dy = direction == 'down'
            ? step
            : (direction == 'up' ? -step : 0.0);
        rect = rect.translate(dx, dy);
      }
      region.bbox = clampBox(rect, _imageSize.width, _imageSize.height);
      region.edited = true;
    }, deferApply: true);
  }

  /// Удалить выделенный регион (Delete).
  void deleteSelectedRegion() {
    final id = _selectedRegionId;
    if (id == null) return;
    editDocument((document) {
      final list = document.data['regions'];
      if (list is List) {
        list.removeWhere((item) => item is Map && '${item['id']}' == id);
      }
    }, deferApply: true);
    selectRegion(null);
  }

  // ---- инспектор: шрифты и стили проекта ------------------------------------

  List<Map<String, dynamic>> get fonts => _fonts;

  /// Семейство Flutter для id шрифта каталога (null — не загружено).
  String? fontFamilyFor(String? fontId) {
    if (fontId == null || fontId.isEmpty) return null;
    return _fontFamilies[fontId];
  }

  int get fontMin => _fontMin;
  int get fontMax => _fontMax;

  /// Границы кегля из настроек (min_font_size / max_font_size).
  void setFontBounds(int min, int max) {
    final nextMin = min > 0 ? min : 10;
    final nextMax = max >= nextMin ? max : nextMin;
    if (_fontMin == nextMin && _fontMax == nextMax) return;
    _fontMin = nextMin;
    _fontMax = nextMax;
    _notify();
  }

  /// Список шрифтов каталога + регистрация файлов в Flutter (идемпотентно).
  Future<void> ensureFonts() async {
    if (_fontsRequested) return;
    final api = _api;
    if (api == null) return;
    _fontsRequested = true;
    try {
      final data = await api.getJson('/api/fonts');
      final raw = data['fonts'];
      _fonts = [
        if (raw is List)
          for (final item in raw)
            if (item is Map) item.cast<String, dynamic>(),
      ];
      _notify();
    } catch (_) {
      _fonts = const [];
      _fontsRequested = false;
      return;
    }
    for (final font in _fonts) {
      final id = '${font['id'] ?? ''}';
      if (id.isEmpty || _fontFamilies.containsKey(id)) continue;
      try {
        final bytes = await api.getBytes(
          '/api/fonts/${Uri.encodeComponent(id)}/file',
        );
        final family =
            'ilt-font-${id.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_')}';
        final loader = FontLoader(family)
          ..addFont(Future.value(ByteData.sublistView(bytes)));
        await loader.load();
        _fontFamilies[id] = family;
        _notify();
      } catch (_) {
        // шрифт не загрузился — образец без него, правка не блокируется
      }
    }
  }

  List<Map<String, dynamic>> get styleLibrary => _styleLibrary;

  bool get hasStyleClipboard => _styleClipboard != null;

  /// Загрузить стили проекта при смене проекта (пустой id — сброс).
  Future<void> ensureStyles(String projectId) async {
    if (projectId == _styleProjectId && _styleLibraryLoaded) return;
    _styleProjectId = projectId;
    _styleLibraryLoaded = false;
    if (projectId.isEmpty) {
      _styleLibrary = const [];
      _notify();
      return;
    }
    final api = _api;
    if (api == null) return;
    try {
      final data = await api.getJson('/api/project/styles');
      _styleLibrary = _parseStyles(data['styles']);
      _styleLibraryLoaded = true;
      _notify();
    } catch (_) {
      _styleLibrary = const [];
    }
  }

  List<Map<String, dynamic>> _parseStyles(Object? raw) => [
    if (raw is List)
      for (final item in raw)
        if (item is Map) item.cast<String, dynamic>(),
  ];

  /// Сохранить стиль выделенного региона в стили проекта.
  Future<bool> saveProjectStyle() async {
    final api = _api;
    final style = _document?.findRegion(_selectedRegionId)?.data['style'];
    if (api == null || _styleProjectId.isEmpty || style is! Map) return false;
    final entry = <String, dynamic>{
      'name': 'Стиль ${_styleLibrary.length + 1}',
      'style': deepCopyMap(style.cast<String, dynamic>()),
    };
    final next = [..._styleLibrary, entry];
    try {
      final data = await api.putJson('/api/project/styles', {'styles': next});
      _styleLibrary = _parseStyles(data['styles']);
      _styleLibraryLoaded = true;
      _notify();
      return true;
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
      _notify();
      return false;
    } catch (error) {
      _errorText = 'Не удалось сохранить стиль: $error';
      _notify();
      return false;
    }
  }

  // ---- инспектор: тексты (немедленное сохранение) ---------------------------

  /// Правка поля региона с сохранением: текст/перевод/говорящий — пауза 500 мс
  /// и коалесинг на поле; другие поля — сразу (зеркало `onField` веба).
  bool _editRegionField(
    String id,
    void Function(Region region) mutator, {
    String coalesce = '',
    int debounceMs = 0,
    bool deferApply = false,
  }) {
    return editDocument(
      (document) {
        final region = document.findRegion(id);
        if (region == null) return;
        region.edited = true;
        mutator(region);
      },
      deferApply: deferApply,
      coalesce: coalesce,
      debounceMs: debounceMs,
    );
  }

  bool setRegionText(String id, String text) => _editRegionField(
    id,
    (region) => region.data['text'] = text,
    coalesce: 'text:$id',
    debounceMs: 500,
  );

  bool setRegionTranslation(String id, String text) => _editRegionField(
    id,
    (region) {
      region.data['translation'] = text;
      region.data['translation_locked'] = text.trim().isNotEmpty;
    },
    coalesce: 'translation:$id',
    debounceMs: 500,
  );

  bool setRegionSpeaker(String id, String text) => _editRegionField(
    id,
    (region) => region.data['speaker'] = text,
    coalesce: 'speaker:$id',
    debounceMs: 500,
  );

  bool setRegionType(String id, String type) => _editRegionField(id, (region) {
    region.data['type'] = type;
    region.data['block_type'] = type;
  });

  // ---- инспектор: стиль (черновик до «Готово») ------------------------------

  bool _patchRegionStyle(
    String id,
    void Function(Map<String, dynamic> style, Region region) patch, {
    String coalesce = '',
  }) {
    final changed = editDocument(
      (document) {
        final region = document.findRegion(id);
        if (region == null) return;
        region.edited = true;
        patch(region.styleMap(create: true), region);
      },
      deferApply: true,
      coalesce: coalesce,
    );
    if (changed) _schedulePreview();
    return changed;
  }

  Map<String, dynamic> _warpCopy(Map<String, dynamic> style) =>
      style['warp'] is Map
      ? Map<String, dynamic>.from(
          (style['warp'] as Map).cast<String, dynamic>(),
        )
      : <String, dynamic>{};

  /// Кегль: 0 (пусто) — авто; иначе кламп в границы настроек.
  bool setRegionFontSize(String id, int? value) {
    final size = value == null || value <= 0
        ? 0
        : value.clamp(_fontMin, _fontMax).toInt();
    return _patchRegionStyle(
      id,
      (style, _) => style['font_size_override'] = size,
      coalesce: 'font:$id',
    );
  }

  bool toggleRegionUppercase(String id) => _patchRegionStyle(
    id,
    (style, _) => style['uppercase'] = !(style['uppercase'] == true),
    coalesce: 'uppercase:$id',
  );

  /// Чернила: чёрный/белый — фиксированный цвет заливки.
  bool setRegionInk(String id, {required bool white}) =>
      _patchRegionStyle(id, (style, _) {
        style['fill_rgb'] = white ? [255, 255, 255] : [0, 0, 0];
        style['fill_locked'] = true;
      }, coalesce: 'ink:$id');

  bool setRegionFontId(String id, String fontId) => _patchRegionStyle(
    id,
    (style, _) => style['font_id'] = fontId,
    coalesce: 'fontid:$id',
  );

  bool setRegionFillRgb(String id, List<int> rgb) =>
      _patchRegionStyle(id, (style, _) {
        style['fill_rgb'] = List<int>.of(rgb);
        style['fill_locked'] = true;
      }, coalesce: 'fill:$id');

  bool setRegionStrokeRgb(String id, List<int> rgb) =>
      _patchRegionStyle(id, (style, _) {
        style['stroke_rgb'] = List<int>.of(rgb);
        style['stroke_mode'] = 'custom';
      }, coalesce: 'stroke:$id');

  bool setRegionStrokeWidth(String id, num width) {
    final value = width > 0 ? width.toDouble() : 0.0;
    return _patchRegionStyle(id, (style, _) {
      style['stroke_width'] = value;
      if (value > 0) style['stroke_mode'] = 'custom';
    }, coalesce: 'strokew:$id');
  }

  bool setRegionRotation(String id, double degrees) => _patchRegionStyle(
    id,
    (style, _) => style['rotation'] = degrees,
    coalesce: 'rotate:$id',
  );

  /// Пресет искривления (зеркало `applyCardWarp` веба).
  bool setRegionWarpPreset(String id, String preset) =>
      _patchRegionStyle(id, (style, region) {
        final warp = _warpCopy(style);
        final bend = warp['bend'];
        final current = bend is num ? bend.toDouble() : 0.0;
        final bw = region.bbox.width <= 0 ? 100.0 : region.bbox.width;
        final bh = region.bbox.height <= 0 ? 100.0 : region.bbox.height;
        switch (preset) {
          case 'none':
            warp
              ..['kind'] = 'none'
              ..['bend'] = 0.0
              ..['quad'] = null
              ..['mesh'] = null;
          case 'arc-up':
            warp
              ..['kind'] = 'arc'
              ..['bend'] = 0.35;
          case 'arc-down':
            warp
              ..['kind'] = 'arc'
              ..['bend'] = -0.35;
          case 'ring':
            warp['kind'] = 'ring';
            warp['bend'] = current == 0 ? 0.35 : current;
          case 'wave':
            warp
              ..['kind'] = 'wave'
              ..['bend'] = 0.35;
          case 'flag':
            warp['kind'] = 'flag';
            warp['bend'] = current == 0 ? 0.25 : current;
          case 'perspective':
            warp['kind'] = 'perspective';
            final quad = warp['quad'];
            warp['quad'] = quad is List && quad.length == 4
                ? quad
                : Region.defaultQuad(bw, bh);
            warp['mesh'] = null;
          case 'mesh':
            warp['kind'] = 'mesh';
            final mesh = warp['mesh'];
            warp['mesh'] = mesh is List && mesh.length == 16
                ? mesh
                : Region.defaultMesh(bw, bh);
            warp['quad'] = null;
        }
        style['warp'] = warp;
      }, coalesce: 'warppreset:$id');

  bool setRegionWarpBend(String id, double bend) =>
      _patchRegionStyle(id, (style, _) {
        final warp = _warpCopy(style);
        warp.putIfAbsent('kind', () => 'none');
        warp.putIfAbsent('quad', () => null);
        warp.putIfAbsent('mesh', () => null);
        warp['bend'] = bend.clamp(-1, 1).toDouble();
        style['warp'] = warp;
      }, coalesce: 'warp:$id');

  /// «Сбросить стили»: поворот и искривление; остальные поля не трогаются.
  bool resetRegionStyle(String id) => _patchRegionStyle(id, (style, _) {
    style['rotation'] = 0.0;
    final warp = _warpCopy(style);
    warp
      ..['kind'] = 'none'
      ..['bend'] = 0.0
      ..['quad'] = null
      ..['mesh'] = null;
    style['warp'] = warp;
  }, coalesce: 'resetstyle:$id');

  /// Наложить стиль проекта/буфера на регион (warp — слиянием).
  bool applyStyleToRegion(String id, Map<String, dynamic> incoming) =>
      _patchRegionStyle(id, (style, _) {
        for (final entry in incoming.entries) {
          if (entry.value == null) continue;
          if (entry.key == 'warp' && entry.value is Map) {
            style['warp'] = {
              ..._warpCopy(style),
              ...(entry.value as Map).cast<String, dynamic>(),
            };
            continue;
          }
          style[entry.key] = deepCopy(entry.value);
        }
      }, coalesce: 'styleapply:$id');

  /// Копировать стиль выделенного региона в буфер сессии.
  void copyStyle() {
    final style = _document?.findRegion(_selectedRegionId)?.data['style'];
    if (style is! Map || style.isEmpty) return;
    _styleClipboard = deepCopyMap(style.cast<String, dynamic>());
    _notify();
  }

  /// Вставить скопированный стиль в выделенный регион (в черновик).
  bool pasteStyle() {
    final style = _styleClipboard;
    final id = _selectedRegionId;
    if (style == null || id == null) return false;
    return applyStyleToRegion(id, style);
  }

  // ---- инспектор: действия, звук, страница ----------------------------------

  bool get actionPending => _pendingAction.isNotEmpty;

  bool isActionPending(String regionId) =>
      _pendingAction.isNotEmpty && _pendingActionRegionId == regionId;

  /// Действие региона: распознать / перевести заново / сократить.
  Future<void> regionAction(String id, String action) async {
    final api = _api;
    final pageId = _pageId;
    if (api == null || pageId == null || actionPending) return;
    _pendingActionRegionId = id;
    _pendingAction = action;
    _notify();
    try {
      await api.postJson('/api/pages/$pageId/action', {
        'action': action,
        'region_id': id,
      });
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
    } catch (error) {
      _errorText = 'Не удалось выполнить действие: $error';
    } finally {
      _pendingActionRegionId = '';
      _pendingAction = '';
      _notify();
    }
  }

  /// «Не переводить»: флаг сохраняется сразу (зеркало веба).
  bool toggleRegionSkip(String id) => editDocument((document) {
    final region = document.findRegion(id);
    if (region == null) return;
    region.skip = !region.skip;
    region.edited = true;
  });

  /// Удалить регион из черновика (из карточки или Del).
  bool deleteRegion(String id) {
    final changed = editDocument((document) {
      final list = document.data['regions'];
      if (list is List) {
        list.removeWhere((item) => item is Map && '${item['id']}' == id);
      }
    }, deferApply: true);
    if (changed && _selectedRegionId == id) selectRegion(null);
    return changed;
  }

  String get sfxRegionId => _sfxRegionId;
  String get sfxStatus => _sfxStatus;
  String get sfxMessage => _sfxMessage;

  /// Подобрать стиль звука: применить черновик, затем POST и перечитка.
  Future<void> restyleSfx(String id) async {
    final api = _api;
    final pageId = _pageId;
    if (api == null || pageId == null) return;
    if (_deferredApply || _pendingBody.containsKey(pageId)) {
      commitDeferredEdits();
    }
    _sfxRegionId = id;
    _sfxStatus = 'loading';
    _sfxMessage = '';
    _notify();
    try {
      await whenSaved(pageId);
      await api.postJson(
        '/api/pages/$pageId/regions/${Uri.encodeComponent(id)}/sfx-style',
      );
      final data = await api.getJson('/api/pages/$pageId');
      _applyDetail(pageId, data, force: true);
      _sfxStatus = 'ready';
    } on ApiException catch (error) {
      _sfxStatus = 'error';
      _sfxMessage = apiErrorMessage(error);
      _errorText = _sfxMessage;
    } catch (error) {
      _sfxStatus = 'error';
      _sfxMessage = 'Не удалось подобрать стиль';
      _errorText = _sfxMessage;
    } finally {
      _notify();
    }
  }

  /// «Сбросить правки» страницы: POST reset → очистка истории → перечитка.
  Future<void> resetPage() async {
    final api = _api;
    final pageId = _pageId;
    if (api == null || pageId == null) return;
    try {
      await api.postJson('/api/pages/$pageId/reset');
      _pendingBody.remove(pageId);
      if (_timerPage == pageId) {
        _saveTimer?.cancel();
        _saveTimer = null;
        _timerPage = '';
      }
      _coalesceKey = '';
      _deferredBaselineKey = '';
      _deferredApply = false;
      _deferredStartDepth = -1;
      _histories.remove(pageId);
      _notify();
      await _reloadDetail(pageId, force: true);
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
      _notify();
    } catch (error) {
      _errorText = 'Не удалось сбросить правки: $error';
      _notify();
    }
  }

  // ---- инспектор: предпросмотр стиля ----------------------------------------

  ui.Image? get stylePreviewImage => _stylePreviewImage;
  Offset get stylePreviewOffset => _stylePreviewOffset;
  String get stylePreviewStatus => _stylePreviewStatus;
  String get stylePreviewMessage => _stylePreviewMessage;

  /// Готовая локальная пара: страница без выбранного региона и его RGBA-слой.
  ui.Image? get basePageImage => _basePageImage;
  ui.Image? get textLayerImage => _textLayerImage;
  ui.Image? get overlayLayerImage => _overlayLayerImage;
  Offset get textLayerOrigin => _textLayerOrigin;
  Offset get textLayerAnchor => _textLayerAnchor;
  Offset get overlayLayerOrigin => _overlayLayerOrigin;
  bool get hasLocalPreview =>
      _basePageImage != null &&
      _textLayerImage != null &&
      _localPreviewRegionId == _selectedRegionId;

  /// Запланировать предпросмотр (400 мс; токен против гонок).
  void _schedulePreview() {
    final pageId = _pageId;
    final regionId = _selectedRegionId;
    final region = regionId == null ? null : _document?.findRegion(regionId);
    if (pageId == null || region == null) {
      _clearPreview();
      _notify();
      return;
    }
    if (_prefersLocalPreview(region)) {
      final layoutKey = _regionLayoutKey(pageId, region);
      // Повторный вызов до срабатывания таймера не должен его отменять:
      // иначе подготовка зависает в «Подготавливаем текст».
      if (layoutKey == _localLayoutKey &&
          (_stylePreviewStatus == 'loading-local' ||
              _stylePreviewStatus == 'ready-local')) {
        return;
      }
      _previewTimer?.cancel();
      _previewKey = "";
      _localLayoutKey = layoutKey;
      _stylePreviewStatus = 'loading-local';
      _stylePreviewMessage = 'Подготавливаем текст';
      final token = ++_previewToken;
      _previewTimer = Timer(const Duration(milliseconds: 250), () {
        unawaited(_runLocalPreview(pageId, region.id, layoutKey, token));
      });
      _notify();
      return;
    }
    _previewTimer?.cancel();
    _clearLocalPreview();
    final key =
        '$pageId|${region.id}|${jsonEncode([region.data['style'] ?? const <String, dynamic>{}, region.data['bbox'], region.data['text'], region.data['translation'], region.data['text_position']])}';
    if (key == _previewKey && _stylePreviewStatus != 'idle') return;
    _previewKey = key;
    _previewToken++;
    _stylePreviewStatus = 'loading';
    _stylePreviewMessage = 'Обновляем предпросмотр';
    _previewTimer = Timer(const Duration(milliseconds: 400), () {
      unawaited(_runPreview(pageId, region.id, key));
    });
    _notify();
  }

  /// Подготовить локальный слой для вкладки «Трансформация»: после этого
  /// поворот и позиция текста рисуются без HTTP.
  void prepareLocalPreview(String regionId) {
    if (regionId != _selectedRegionId) return;
    final region = _document?.findRegion(regionId);
    if (region == null) return;
    final kind = '${region.warp?['kind'] ?? 'none'}';
    if (!_localWarpKinds.contains(kind)) return;
    if (_localPreviewRequested) return;
    _localPreviewRequested = true;
    _schedulePreview();
  }

  static const _localWarpKinds = {
    'none',
    'mesh',
    'arc',
    'wave',
    'flag',
    'ring',
    'perspective',
  };

  /// Mesh можно двигать локально: пересобирать страницу на каждое движение
  /// не нужно, пока раскладка (текст, шрифт, bbox) не изменилась.
  bool _prefersLocalPreview(Region region) {
    final warp = region.warp;
    final kind = '${warp?['kind'] ?? 'none'}';
    if (region.bbox.width <= 0 || region.bbox.height <= 0) return false;
    final skew = region.styleMap()['skew_x'];
    if (skew is num && skew.abs() > 1e-6) return false;
    if (kind == 'none') return _localPreviewRequested;
    if (!_localWarpKinds.contains(kind)) return false;
    if (kind == 'mesh' && ((warp?['version'] as num?)?.toInt() ?? 1) < 2) {
      return false;
    }
    if (region.rotation.abs() > 1e-6) {
      // Для arc/wave/flag/ring слой готовится уже повёрнутым, warp — локально.
      return _localPreviewRequested && _localRotationWarps.contains(kind);
    }
    return kind == 'mesh' || _localPreviewRequested;
  }

  static const _localRotationWarps = {'arc', 'wave', 'flag', 'ring'};

  String _regionLayoutKey(String pageId, Region region) {
    final style = <String, dynamic>{...region.styleMap()};
    style.remove('rotation');
    style.remove('warp');
    final kind = '${region.warp?['kind'] ?? 'none'}';
    return jsonEncode([
      pageId,
      region.id,
      region.data['bbox'],
      region.data['bubble_bbox'],
      region.data['class_name'],
      region.data['block_type'],
      region.data['text'],
      region.data['translation'],
      style,
      if (_localRotationWarps.contains(kind)) region.rotation,
      // Композиция ниже/выше выбранной: чужие регионы и их порядок.
      [
        for (final item in _document?.regions ?? const <Region>[])
          if (item.id != region.id) item.data,
      ],
    ]);
  }

  Future<ui.Image?> _decodeImage(ApiBytes response) async {
    final codec = await ui.instantiateImageCodec(response.bytes);
    try {
      final frame = await codec.getNextFrame();
      return frame.image;
    } finally {
      codec.dispose();
    }
  }

  /// Свежий snapshot выбранного региона перед Done: закрывает гонку с preview.
  Future<bool> _refreshDoneSnapshot(String pageId) async {
    final api = _api;
    final regionId = _selectedRegionId;
    final region = _document?.findRegion(regionId);
    if (api == null || regionId == null || region == null) return true;
    final draft = <String, dynamic>{
      'text': region.data['text'],
      'translation': region.data['translation'],
      'bbox': region.data['bbox'],
      'style': region.data['style'],
      'text_position': region.data['text_position'],
      if (region.data['layout_snapshot'] != null)
        'layout_snapshot': region.data['layout_snapshot'],
    };
    final drafts = [
      for (final item in _document?.regions ?? const <Region>[]) item.data,
    ];
    try {
      final data = await api.postJson(
        '/api/pages/$pageId/layout-snapshot',
        {'region_id': regionId, 'draft': draft, 'drafts': drafts},
      );
      if (_disposed || _pageId != pageId) return false;
      final snapshot = data['layout_snapshot'];
      if (snapshot is Map) {
        final current = _document?.findRegion(regionId);
        if (current != null) {
          current.data['layout_snapshot'] =
              snapshot.cast<String, dynamic>();
          _syncPendingSnapshots(pageId);
          _notify();
        }
      }
      return true;
    } on ApiException catch (error) {
      _applyError = apiErrorMessage(error);
      return false;
    }
  }

  /// Перенести производные snapshot из текущего документа в ожидающий PUT.
  void _syncPendingSnapshots(String pageId) {
    final body = _pendingBody[pageId];
    final document = _document;
    final regions = body?['regions'];
    if (document == null || regions is! List) return;
    for (final item in regions) {
      if (item is! Map) continue;
      final current = document.findRegion('${item['id']}');
      if (current == null) continue;
      final snapshot = current.data['layout_snapshot'];
      if (snapshot != null) {
        item['layout_snapshot'] = deepCopyMap(snapshot.cast<String, dynamic>());
      } else {
        item.remove('layout_snapshot');
      }
    }
  }

  /// Сохранить раскладку, показанную preview, чтобы «Готово» не пересобирало
  /// строки при изменившемся повороте или warp.
  void _rememberLayoutSnapshot(String regionId, String? encoded) {
    if (encoded == null || encoded.isEmpty) return;
    final pageId = _pageId;
    final document = _document;
    final region = document?.findRegion(regionId);
    if (pageId == null || document == null || region == null) return;
    try {
      final decoded = jsonDecode(utf8.decode(base64Decode(encoded)));
      if (decoded is! Map) return;
      final snapshot = decoded.cast<String, dynamic>();
      if (snapshot['version'] != 1) return;
      final current = region.data['layout_snapshot'];
      if (current is Map && jsonEncode(current) == jsonEncode(snapshot)) return;
      region.data['layout_snapshot'] = snapshot;
      // Снимок — производные данные preview; сохраняем его вместе со
      // следующим черновиком, но сами по себе правки не создаём.
      if (_deferredApply) _pendingBody[pageId] = deepCopyMap(document.data);
      _notify();
    } catch (_) {
      // Битый заголовок не должен ломать preview.
    }
  }

  Future<void> _runLocalPreview(
    String pageId,
    String regionId,
    String layoutKey,
    int token,
  ) async {
    final api = _api;
    if (api == null) return;
    final region = _document?.findRegion(regionId);
    if (region == null) return;
    final draft = <String, dynamic>{
      'text': region.data['text'],
      'translation': region.data['translation'],
      'bbox': region.data['bbox'],
      'style': region.data['style'],
      'text_position': region.data['text_position'],
      if (region.data['layout_snapshot'] != null)
        'layout_snapshot': region.data['layout_snapshot'],
    };
    final kind = '${region.warp?['kind'] ?? 'none'}';
    final applyRotation =
        _localRotationWarps.contains(kind) && region.rotation.abs() > 1e-6;
    final drafts = [
      for (final item in _document?.regions ?? const <Region>[]) item.data,
    ];
    try {
      final responses = await Future.wait([
        api.postBytes('/api/pages/$pageId/preview-region', {
          'region_id': regionId,
          'draft': draft,
          'drafts': drafts,
          'drafts_complete': true,
          'mode': 'base-page',
        }),
        api.postBytes('/api/pages/$pageId/preview-region', {
          'region_id': regionId,
          'draft': draft,
          'apply_rotation': applyRotation,
          'mode': 'base-layer',
        }),
        api.postBytes('/api/pages/$pageId/preview-region', {
          'region_id': regionId,
          'draft': draft,
          'drafts': drafts,
          'drafts_complete': true,
          'mode': 'base-overlay',
        }),
      ]);
      final basePage = await _decodeImage(responses[0]);
      final layer = await _decodeImage(responses[1]);
      final overlay = await _decodeImage(responses[2]);
      if (_disposed ||
          token != _previewToken ||
          layoutKey != _localLayoutKey ||
          pageId != _pageId) {
        basePage?.dispose();
        layer?.dispose();
        overlay?.dispose();
        return;
      }
      if (basePage == null || layer == null || overlay == null) {
        basePage?.dispose();
        layer?.dispose();
        overlay?.dispose();
        _localPreviewError('Не удалось декодировать слой текста');
        return;
      }
      _basePageImage?.dispose();
      _textLayerImage?.dispose();
      _overlayLayerImage?.dispose();
      _basePageImage = basePage;
      _textLayerImage = layer;
      _overlayLayerImage = overlay;
      _overlayLayerOrigin = Offset(
        double.tryParse(responses[2].headers['x-offset-x'] ?? '') ?? 0,
        double.tryParse(responses[2].headers['x-offset-y'] ?? '') ?? 0,
      );
      // Локальная пара заменила старый exact-preview.
      _stylePreviewImage?.dispose();
      _stylePreviewImage = null;
      _stylePreviewOffset = Offset.zero;
      _textLayerOrigin = Offset(
        double.tryParse(responses[1].headers['x-offset-x'] ?? '') ?? 0,
        double.tryParse(responses[1].headers['x-offset-y'] ?? '') ?? 0,
      );
      _textLayerAnchor = Offset(
        double.tryParse(responses[1].headers['x-layer-anchor-x'] ?? '') ??
            _textLayerOrigin.dx,
        double.tryParse(responses[1].headers['x-layer-anchor-y'] ?? '') ??
            _textLayerOrigin.dy,
      );
      _localPreviewRegionId = regionId;
      _rememberLayoutSnapshot(
        regionId,
        responses[1].headers['x-layout-snapshot'],
      );
      _stylePreviewStatus = 'ready-local';
      _stylePreviewMessage = '';
    } on ApiException catch (error) {
      if (token != _previewToken) return;
      _localPreviewError(apiErrorMessage(error));
    } catch (_) {
      if (token != _previewToken) return;
      _localPreviewError('Не удалось подготовить текст');
    } finally {
      if (token == _previewToken) _notify();
    }
  }

  void _localPreviewError(String message) {
    // Последняя корректная пара остаётся на экране как явно устаревший
    // fallback; статус «local-error» показывает, что это не новый результат.
    _stylePreviewStatus = 'local-error';
    _stylePreviewMessage = message;
  }

  Future<void> _runPreview(String pageId, String regionId, String key) async {
    final api = _api;
    if (api == null) return;
    final token = ++_previewToken;
    final region = _document?.findRegion(regionId);
    if (region == null) {
      _stylePreviewStatus = 'idle';
      _stylePreviewMessage = '';
      _notify();
      return;
    }
    final draft = <String, dynamic>{
      'text': region.data['text'],
      'translation': region.data['translation'],
      'bbox': region.data['bbox'],
      'style': region.data['style'],
      'text_position': region.data['text_position'],
      if (region.data['layout_snapshot'] != null)
        'layout_snapshot': region.data['layout_snapshot'],
    };
    try {
      final response = await api.postBytes(
        '/api/pages/$pageId/preview-region',
        {'region_id': regionId, 'draft': draft},
      );
      final codec = await ui.instantiateImageCodec(response.bytes);
      late final ui.FrameInfo frame;
      try {
        frame = await codec.getNextFrame();
      } finally {
        codec.dispose();
      }
      if (_disposed ||
          token != _previewToken ||
          key != _previewKey ||
          pageId != _pageId) {
        frame.image.dispose();
        return;
      }
      final x = double.tryParse(response.headers['x-offset-x'] ?? '') ?? 0;
      final y = double.tryParse(response.headers['x-offset-y'] ?? '') ?? 0;
      _stylePreviewImage?.dispose();
      _stylePreviewImage = frame.image;
      _stylePreviewOffset = Offset(x, y);
      _rememberLayoutSnapshot(regionId, response.headers['x-layout-snapshot']);
      _stylePreviewStatus = 'ready';
      _stylePreviewMessage = '';
    } on ApiException catch (error) {
      if (token != _previewToken) return;
      _stylePreviewImage?.dispose();
      _stylePreviewImage = null;
      _stylePreviewStatus = 'error';
      _stylePreviewMessage = apiErrorMessage(error);
    } catch (_) {
      if (token != _previewToken) return;
      _stylePreviewImage?.dispose();
      _stylePreviewImage = null;
      _stylePreviewStatus = 'error';
      _stylePreviewMessage = 'Не удалось обновить предпросмотр';
    } finally {
      if (token == _previewToken) _notify();
    }
  }

  void _clearLocalPreview() {
    _basePageImage?.dispose();
    _basePageImage = null;
    _textLayerImage?.dispose();
    _textLayerImage = null;
    _overlayLayerImage?.dispose();
    _overlayLayerImage = null;
    _textLayerOrigin = Offset.zero;
    _textLayerAnchor = Offset.zero;
    _overlayLayerOrigin = Offset.zero;
    _localLayoutKey = '';
    _localPreviewRegionId = '';
  }

  void _clearPreview() {
    _previewTimer?.cancel();
    _previewTimer = null;
    _previewToken++;
    _previewKey = '';
    _stylePreviewImage?.dispose();
    _stylePreviewImage = null;
    _stylePreviewOffset = Offset.zero;
    _stylePreviewStatus = 'idle';
    _stylePreviewMessage = '';
    _clearLocalPreview();
  }

  // ---- страж ухода со страницы --------------------------------------------
  /// Запустить действие с проверкой черновика. Если черновик есть — поднимает
  /// диалог; действие выполнится после решения пользователя.
  Future<void> guardOrRun(Future<void> Function() action) async {
    if (!_deferredApply) {
      await action();
      return;
    }
    _pendingLeave = action;
    _leaveCompleter ??= Completer<bool>();
    _notify();
  }

  /// «Применить» в диалоге ухода: сохранить черновик, затем выполнить действие.
  Future<void> commitLeave() async {
    final action = _pendingLeave;
    final pageId = _pageId;
    commitDeferredEdits();
    if (pageId != null) await whenSaved(pageId);
    _pendingLeave = null;
    final completer = _leaveCompleter;
    _leaveCompleter = null;
    _notify();
    if (action != null) await action();
    completer?.complete(true);
  }

  /// «Отменить правки»: перечитать документ и выполнить действие.
  Future<void> discardLeave() async {
    final action = _pendingLeave;
    await discardDeferredEdits();
    _pendingLeave = null;
    final completer = _leaveCompleter;
    _leaveCompleter = null;
    _notify();
    if (action != null) await action();
    completer?.complete(true);
  }

  /// «Остаться»: ничего не делать.
  void cancelLeave() {
    _cancelLeave(true);
  }

  void _cancelLeave(bool complete) {
    final action = _pendingLeave;
    _pendingLeave = null;
    final completer = _leaveCompleter;
    _leaveCompleter = null;
    if (complete) _notify();
    if (action != null || completer != null) {
      completer?.complete(false);
    }
  }

  /// Гарантировать разрешение черновика перед выходом (для ShellState).
  Future<bool> ensureDraftResolved() {
    if (!_deferredApply) return Future.value(true);
    _pendingLeave ??= () async {};
    _leaveCompleter ??= Completer<bool>();
    _notify();
    return _leaveCompleter!.future;
  }
}

/// Живая сессия канваса: матрица, зум, предпросмотр жестов.
///
/// Уведомляет только канвас и док — тяжёлые панирования не перестраивают окно.
class CanvasSession extends ChangeNotifier {
  CanvasSession({required this.onChanged});

  /// Колбэк для проброса «лёгких» изменений (зум-режим) в состояние.
  final void Function() onChanged;

  /// Отменить текущий жест на канвасе (Esc); null, если жеста нет.
  bool Function()? onCancelGesture;

  ViewTransform _transform = const ViewTransform();
  Object _zoomMode = 'fit';
  ui.Size _viewport = ui.Size.zero;
  ui.Size _imageSize = ui.Size.zero;

  /// Пустой запас сверху/снизу как доля высоты листа (028): край листа можно
  /// «отодвинуть» от края окна на ¼ высоты.
  static const double _verticalMargin = 0.25;

  /// После смены страницы ждём реальный размер нового листа, чтобы заново
  /// поставить его к верхнему краю (веб: `scrollHome` до `onImageLoad`).
  bool _pinHome = false;

  bool spaceDown = false;
  ui.Offset? cursor;
  ui.Rect? draftRect;
  ui.Rect? previewRect;
  String? previewRegionId;
  double? previewRotation;
  String? previewWarpId;
  List<ui.Offset>? previewWarpPoints;
  String? previewTextId;
  Offset? previewTextOffset;
  Offset? lassoHover;

  ViewTransform get transform => _transform;
  Object get zoomMode => _zoomMode;
  ui.Size get viewport => _viewport;
  ui.Size get imageSize => _imageSize;

  String get zoomLabel {
    if (_zoomMode == 'fit') return 'Вписать';
    if (_zoomMode == 'fit-width') return 'По ширине';
    return '${(_transform.scale * 100).round()} %';
  }

  void setViewport(ui.Size size) {
    if (_viewport == size) return;
    _viewport = size;
    if (_zoomMode == 'fit' || _zoomMode == 'fit-width') _recompute();
  }

  void setImageSize(ui.Size size) {
    if (size.isEmpty || _imageSize == size) return;
    _imageSize = size;
    if (_pinHome) {
      _pinHome = false;
      _recompute();
      return;
    }
    if (_zoomMode == 'fit' || _zoomMode == 'fit-width') _recompute();
  }

  /// Смена страницы: числовой зум сохраняется, лист возвращается к верхнему
  /// краю (веб: `scrollTop/scrollLeft = 0`); черновики жестов сбрасываются.
  void homeForPage() {
    _pendingScrollLeft = null;
    _pendingScrollTop = null;
    clearPreviews();
    clearLasso();
    cursor = null;
    _pinHome = _zoomMode is num;
    _recompute();
  }

  /// Новая страница: зум «вписать», предпросмотры очищены.
  void resetForPage() {
    _zoomMode = 'fit';
    _transform = const ViewTransform();
    _pendingScrollLeft = null;
    _pendingScrollTop = null;
    clearPreviews();
    clearLasso();
    cursor = null;
    notifyListeners();
  }

  double? _pendingScrollLeft;
  double? _pendingScrollTop;

  /// Восстановить сессию просмотра из пакета (зум + смещение).
  void restoreSession(Object zoom, double scrollLeft, double scrollTop) {
    _pinHome = false;
    _zoomMode = zoom;
    _pendingScrollLeft = scrollLeft;
    _pendingScrollTop = scrollTop;
    _recompute();
  }

  void _recompute() {
    if (_imageSize.isEmpty || _viewport.isEmpty) return;
    final next = switch (_zoomMode) {
      'fit' => ViewTransform.fit(_imageSize, _viewport),
      'fit-width' => ViewTransform.fitWidth(_imageSize, _viewport),
      _ => ViewTransform(
        scale: (_zoomMode as num).toDouble().clamp(
          ViewTransform.minScale,
          ViewTransform.maxScale,
        ),
      ),
    };
    var target = next.clamped(
      _imageSize,
      _viewport,
      verticalMargin: _verticalMargin,
    );
    final left = _pendingScrollLeft;
    final top = _pendingScrollTop;
    if (left != null && top != null) {
      _pendingScrollLeft = null;
      _pendingScrollTop = null;
      target = ViewTransform(
        scale: next.scale,
        tx: -left,
        ty: -top,
      ).clamped(_imageSize, _viewport, verticalMargin: _verticalMargin);
    }
    _transform = target;
    notifyListeners();
    onChanged();
  }

  void setZoom(Object mode) {
    _zoomMode = mode;
    if (mode is num && !_imageSize.isEmpty && !_viewport.isEmpty) {
      _transform = _transform
          .zoomAt(mode.toDouble(), _viewport.center(ui.Offset.zero))
          .clamped(_imageSize, _viewport, verticalMargin: _verticalMargin);
      notifyListeners();
      onChanged();
      return;
    }
    _recompute();
  }

  void fit() => setZoom('fit');

  void fitWidth() => setZoom('fit-width');

  void zoom100() => setZoom(1.0);

  void zoomStep(int direction, {ui.Offset? focal}) {
    final next = ViewTransform.stepFrom(_transform.scale, direction);
    _zoomMode = next;
    if (_imageSize.isEmpty || _viewport.isEmpty) {
      notifyListeners();
      onChanged();
      return;
    }
    final center = focal ?? _viewport.center(ui.Offset.zero);
    _transform = _transform
        .zoomAt(next, center)
        .clamped(_imageSize, _viewport, verticalMargin: _verticalMargin);
    notifyListeners();
    onChanged();
  }

  void panBy(ui.Offset delta) {
    if (_imageSize.isEmpty) return;
    final next = _transform
        .translated(delta)
        .clamped(_imageSize, _viewport, verticalMargin: _verticalMargin);
    if (next == _transform) return;
    _transform = next;
    notifyListeners();
  }

  /// Прокрутка колесом (без Ctrl): контент едет против дельты.
  void scrollBy(ui.Offset delta) => panBy(-delta);

  void setSpaceDown(bool value) {
    if (spaceDown == value) return;
    spaceDown = value;
    notifyListeners();
  }

  void setCursor(ui.Offset? value) {
    if (cursor == value) return;
    cursor = value;
    notifyListeners();
  }

  void setDraftRect(ui.Rect? rect) {
    draftRect = rect;
    notifyListeners();
  }

  void setPreviewRect(String? regionId, ui.Rect? rect) {
    previewRegionId = regionId;
    previewRect = rect;
    notifyListeners();
  }

  void setPreviewRotation(String? regionId, double? angle) {
    previewRegionId = regionId;
    previewRotation = angle;
    notifyListeners();
  }

  void setPreviewWarp(String? regionId, List<ui.Offset>? points) {
    previewWarpId = regionId;
    previewWarpPoints = points;
    notifyListeners();
  }

  void setPreviewText(String? regionId, Offset? offset) {
    previewTextId = regionId;
    previewTextOffset = offset;
    notifyListeners();
  }

  void setLassoHover(ui.Offset? point) {
    lassoHover = point;
    notifyListeners();
  }

  bool cancelGesture() {
    final callback = onCancelGesture;
    if (callback == null || !callback()) return false;
    clearPreviews();
    return true;
  }

  void clearPreviews() {
    draftRect = null;
    previewRect = null;
    previewRegionId = null;
    previewRotation = null;
    previewWarpId = null;
    previewWarpPoints = null;
    previewTextId = null;
    previewTextOffset = null;
    notifyListeners();
  }

  void clearLasso() {
    lasso = const [];
    lassoHover = null;
    notifyListeners();
  }

  List<ui.Offset> lasso = const [];
  String lassoMode = Stroke.fill;
  List<ui.Offset> strokePoints = const [];
  String strokeMode = Stroke.paint;

  void beginStroke(String mode, ui.Offset point) {
    strokeMode = mode;
    strokePoints = [point];
    notifyListeners();
  }

  void addStrokePoint(ui.Offset point) {
    final last = strokePoints.isEmpty ? null : strokePoints.last;
    if (last != null &&
        (last.dx - point.dx).abs() < 1 &&
        (last.dy - point.dy).abs() < 1) {
      return;
    }
    strokePoints = [...strokePoints, point];
    notifyListeners();
  }

  void clearStroke() {
    strokePoints = const [];
    notifyListeners();
  }

  void addLassoPoint(ui.Offset point) {
    final last = lasso.isEmpty ? null : lasso.last;
    if (last != null &&
        (last.dx - point.dx).abs() < 1 &&
        (last.dy - point.dy).abs() < 1) {
      return;
    }
    lasso = [...lasso, point];
    notifyListeners();
  }
}
