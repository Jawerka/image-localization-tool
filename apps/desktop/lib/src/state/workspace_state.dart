import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import '../api/errors.dart';
import '../api/ilt_api.dart';
import 'viewer_state.dart';

/// Открытый проект (из bootstrap/collection).
class ProjectInfo {
  const ProjectInfo({required this.id, required this.name});

  final String id;
  final String name;

  static ProjectInfo? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final id = raw['id'];
    if (id is! String || id.isEmpty) return null;
    final name = raw['name'];
    return ProjectInfo(id: id, name: name is String ? name : '');
  }
}

/// Нормализованный статус страницы (как `normalizeStatus` в web).
String normalizePageStatus(Object? raw) {
  final value = '${raw ?? 'idle'}'.toLowerCase();
  if (value == 'queue' || value == 'queued') return 'queued';
  if (value == 'run' || value == 'running' || value == 'working') {
    return 'running';
  }
  if (value == 'ready' || value == 'done') return 'done';
  if (value == 'edit' || value == 'edited') return 'edited';
  if (value == 'no_llm' || value == 'offline') return 'offline';
  if (value == 'failed' || value == 'error') return 'error';
  return 'idle';
}

/// Строка страницы: bootstrap/collection плюс живые события.
class PageRow {
  const PageRow({
    required this.id,
    required this.name,
    this.chapter = '',
    this.status = 'idle',
    this.progress = 0,
    this.stage = '',
    this.error = '',
    this.warnings = const [],
    this.overflow = false,
  });

  final String id;
  final String name;
  final String chapter;
  final String status;
  final int progress;
  final String stage;
  final String error;
  final List<String> warnings;
  final bool overflow;

  factory PageRow.fromJson(Map<String, dynamic> json) => PageRow(
        id: '${json['id'] ?? ''}',
        name: '${json['name'] ?? ''}',
        chapter: '${json['chapter'] ?? ''}',
        status: normalizePageStatus(json['status']),
        progress: (json['progress'] as num?)?.toInt() ?? 0,
        stage: '${json['stage'] ?? ''}',
        error: '${json['error'] ?? ''}',
        warnings: [
          for (final item in (json['warnings'] as List? ?? const [])) '$item',
        ],
        overflow: json['overflow'] == true,
      );

  /// Слияние частичного `page.updated`.
  PageRow merge(Map<String, dynamic> data) => PageRow(
        id: id,
        name: name,
        chapter: chapter,
        status: data.containsKey('status')
            ? normalizePageStatus(data['status'])
            : status,
        progress: (data['progress'] as num?)?.toInt() ?? progress,
        stage: data.containsKey('stage') ? '${data['stage']}' : stage,
        error: data.containsKey('error') ? '${data['error']}' : error,
        warnings: warnings,
        overflow: data.containsKey('overflow')
            ? data['overflow'] == true
            : overflow,
      );

  PageRow copyWith({String? status, int? progress, String? stage, String? error}) =>
      PageRow(
        id: id,
        name: name,
        chapter: chapter,
        status: status ?? this.status,
        progress: progress ?? this.progress,
        stage: stage ?? this.stage,
        error: error ?? this.error,
        warnings: warnings,
        overflow: overflow,
      );

  bool get isReady =>
      status == 'done' || status == 'edited' || status == 'offline';
  bool get isRunning => status == 'running';
  bool get isQueued => status == 'queued';
  bool get isProblem => status == 'error' || error.isNotEmpty;
}

/// Пункт списка «Недавние проекты».
class RecentEntry {
  const RecentEntry({required this.id, this.name = '', this.path = ''});

  final String id;
  final String name;
  final String path;

  factory RecentEntry.fromJson(Map<String, dynamic> json) => RecentEntry(
        id: '${json['id'] ?? ''}',
        name: '${json['name'] ?? ''}',
        path: '${json['path'] ?? ''}',
      );
}

/// Счётчики пакетного прогона (выводятся из строк страниц).
class BatchCounts {
  const BatchCounts({
    required this.total,
    required this.done,
    required this.running,
    required this.queued,
    required this.errors,
    required this.offline,
  });

  factory BatchCounts.from(List<PageRow> pages) {
    var done = 0;
    var running = 0;
    var queued = 0;
    var errors = 0;
    var offline = 0;
    for (final page in pages) {
      switch (page.status) {
        case 'done':
        case 'edited':
          done += 1;
        case 'running':
          running += 1;
        case 'queued':
          queued += 1;
        case 'error':
          errors += 1;
        case 'offline':
          offline += 1;
      }
    }
    return BatchCounts(
      total: pages.length,
      done: done,
      running: running,
      queued: queued,
      errors: errors,
      offline: offline,
    );
  }

  final int total;
  final int done;
  final int running;
  final int queued;
  final int errors;
  final int offline;

  int get finished => done + offline;

  int get percent => total == 0 ? 0 : ((finished * 100) / total).round();
}

/// Данные главного окна: проект, страницы, недавние, выбор и batch.
///
/// Слушает только API; соединением и событиями владеет `ShellState`.
class WorkspaceState extends ChangeNotifier {
  WorkspaceState() {
    viewer.addListener(notifyListeners);
    viewer.onLayersChanged = _persistLayers;
  }

  IltApi? _api;

  /// Просмотрщик активной страницы: документ, правки, инструменты.
  final ViewerState viewer = ViewerState();

  ProjectInfo? _project;
  List<PageRow> _pages = const [];
  List<RecentEntry> _recent = const [];
  Map<String, dynamic> _settings = const {};
  Map<String, dynamic>? _preview;
  Map<String, dynamic>? _pendingLayerSettings;
  bool _savingLayers = false;
  Map<String, dynamic> _llm = const {};
  String _device = '';
  String _version = '';
  bool _modelsReady = true;
  bool _paused = false;
  bool _unfinished = false;
  String _query = '';
  bool _problemsOnly = false;
  String? _activeId;
  final Set<String> _selected = <String>{};
  String? _errorText;
  bool _dirtyClose = false;
  bool _busyAction = false;
  String _mode = 'retouch';

  ProjectInfo? get project => _project;
  List<PageRow> get pages => _pages;
  List<RecentEntry> get recent => _recent;
  Map<String, dynamic> get llm => _llm;

  /// Настройки из bootstrap (без учёта черновика).
  Map<String, dynamic> get settings => _settings;

  /// Значение с учётом черновика настроек (live-preview).
  Object? effective(String key) {
    final preview = _preview;
    if (preview != null && preview.containsKey(key)) return preview[key];
    return _settings[key];
  }

  /// Тема: dark / light / system.
  String get themeName {
    final raw = effective('theme');
    return raw is String && raw.isNotEmpty ? raw : 'dark';
  }

  /// Масштаб интерфейса 100–150 → 1.0–1.5.
  double get uiScale {
    final raw = effective('ui_scale');
    final value = raw is num ? raw.toDouble() : 100;
    return value.clamp(100, 150) / 100;
  }

  String get sourceLang {
    final raw = effective('source_lang');
    return raw is String && raw.isNotEmpty ? raw : 'en';
  }

  String get targetLang {
    final raw = effective('target_lang');
    return raw is String && raw.isNotEmpty ? raw : 'ru';
  }

  bool get firstRunComplete => _settings['first_run_complete'] == true;

  /// Черновик настроек для live-preview (тема/масштаб) до «ОК».
  void previewSettings(Map<String, dynamic> draft) {
    _preview = draft;
    notifyListeners();
  }

  /// Отменить черновик (кнопка «Отмена»).
  void clearPreview() {
    if (_preview == null) return;
    _preview = null;
    notifyListeners();
  }
  String get device => _device;
  String get version => _version;
  bool get modelsReady => _modelsReady;
  bool get paused => _paused;
  bool get unfinished => _unfinished;
  String get query => _query;
  bool get problemsOnly => _problemsOnly;
  String? get activeId => _activeId;
  Set<String> get selectedIds => Set.unmodifiable(_selected);
  String? get errorText => _errorText;
  bool get dirtyClose => _dirtyClose;
  bool get busyAction => _busyAction;
  bool get hasProject => _project != null;
  String get mode => _mode;

  /// Док канваса у верхнего края (настройка `dock_position`).
  bool get dockAtTop => _settings['dock_position'] == 'top';

  PageRow? get activePage {
    for (final page in _pages) {
      if (page.id == _activeId) return page;
    }
    return null;
  }

  BatchCounts get batch => BatchCounts.from(_pages);

  /// Есть незавершённые страницы — идёт или ждёт прогон.
  bool get busy =>
      _pages.any((page) => page.isQueued || page.isRunning);

  /// Процент задания для пилюли в верхней панели.
  int get jobPercent => batch.percent;

  /// Страницы после поиска и фильтра «Проблемы».
  List<PageRow> get visiblePages {
    var rows = _pages;
    final text = _query.trim().toLowerCase();
    if (text.isNotEmpty) {
      rows = [
        for (final page in rows)
          if (page.name.toLowerCase().contains(text)) page,
      ];
    }
    if (_problemsOnly) {
      rows = [for (final page in rows) if (page.isProblem) page];
    }
    return rows;
  }

  void bind(IltApi api) {
    _api = api;
    _errorText = null;
    _dirtyClose = false;
    viewer.bind(api);
    notifyListeners();
  }

  /// Сброс при остановке сайдкара/перезапуске.
  void detach() {
    _api = null;
    _project = null;
    _pages = const [];
    _recent = const [];
    _settings = const {};
    _preview = null;
    _llm = const {};
    _device = '';
    _version = '';
    _modelsReady = true;
    _paused = false;
    _unfinished = false;
    _activeId = null;
    _selected.clear();
    _errorText = null;
    _dirtyClose = false;
    _busyAction = false;
    viewer.detach();
    notifyListeners();
  }

  @override
  void dispose() {
    viewer.removeListener(notifyListeners);
    viewer.dispose();
    super.dispose();
  }

  void applyBootstrap(Map<String, dynamic> data) {
    _project = ProjectInfo.tryParse(data['project']);
    _pages = _parsePages(data['pages']);
    _recent = _parseRecent(data['recent']);
    final settings = data['settings'];
    _settings = settings is Map ? settings.cast<String, dynamic>() : const {};
    _preview = null;
    final llm = data['llm'];
    _llm = llm is Map ? llm.cast<String, dynamic>() : const {};
    _device = data['device'] is String ? data['device'] as String : '';
    _version = data['version'] is String ? data['version'] as String : '';
    _modelsReady = data['models_ready'] == true;
    _errorText = null;
    _pruneSelection();
    _syncViewerLayers();
    _syncViewerPage();
    _syncViewerInspector();
    notifyListeners();
  }

  void applyCollection(Map<String, dynamic> data) {
    if (data.containsKey('project')) {
      _project = ProjectInfo.tryParse(data['project']);
    }
    if (data.containsKey('pages')) {
      _pages = _parsePages(data['pages']);
    }
    _pruneSelection();
    _dirtyClose = false;
    _syncViewerPage();
    _syncViewerInspector();
    notifyListeners();
  }

  /// Применить сохранённую видимость слоёв; старые настройки — оба включены.
  void _syncViewerLayers() {
    final boxes = _settings['viewer_show_boxes'];
    final mask = _settings['viewer_show_mask'];
    viewer.restoreLayers(
      boxes: boxes is bool ? boxes : true,
      mask: mask is bool ? mask : true,
    );
  }

  /// Сохранить слои: последний патч побеждает, запросы идут по одному.
  void _persistLayers(bool boxes, bool mask) {
    _settings = {
      ..._settings,
      'viewer_show_boxes': boxes,
      'viewer_show_mask': mask,
    };
    _pendingLayerSettings = {
      'viewer_show_boxes': boxes,
      'viewer_show_mask': mask,
    };
    unawaited(_flushLayerSettings());
  }

  Future<void> _flushLayerSettings() async {
    if (_savingLayers) return;
    final api = _api;
    if (api == null) {
      _pendingLayerSettings = null;
      return;
    }
    _savingLayers = true;
    try {
      while (_pendingLayerSettings != null) {
        final patch = _pendingLayerSettings!;
        _pendingLayerSettings = null;
        try {
          await api.putJson('/api/settings', patch);
        } on ApiException catch (error) {
          _errorText = apiErrorMessage(error);
          notifyListeners();
          // Более новое переключение не теряем: пробуем отправить его.
          if (_pendingLayerSettings == null) return;
        } catch (error) {
          _errorText = 'Не удалось сохранить слои: $error';
          notifyListeners();
          if (_pendingLayerSettings == null) return;
        }
      }
    } finally {
      _savingLayers = false;
    }
  }

  /// Дождаться записи слоёв перед штатным выходом.
  Future<void> whenLayersSaved() async {
    while (_savingLayers || _pendingLayerSettings != null) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
  }

  /// Границы кегля и стили проекта для инспектора (024).
  void _syncViewerInspector() {
    final minRaw = _settings['min_font_size'];
    final maxRaw = _settings['max_font_size'];
    final min = minRaw is num ? minRaw.toInt() : int.tryParse('$minRaw') ?? 10;
    final max = maxRaw is num ? maxRaw.toInt() : int.tryParse('$maxRaw') ?? 128;
    viewer.setFontBounds(min, max);
    unawaited(viewer.ensureStyles(_project?.id ?? ''));
  }

  /// Синхронизировать активную страницу просмотрщика после смены коллекции.
  void _syncViewerPage() {
    if (viewer.pageId == _activeId) return;
    unawaited(viewer.openPage(_activeId));
  }

  /// Живое событие SSE.
  void applyEvent(String event, Map<String, dynamic> data) {
    switch (event) {
      case 'page.updated':
        _mergePage(data);
        _reloadViewerIfClean('${data['page_id'] ?? ''}');
      case 'job.progress':
        _mergeProgress(data);
      case 'llm.status':
        _llm = data;
        notifyListeners();
      case 'worker.failed':
        final message = '${data['error'] ?? data['message'] ?? ''}'.trim();
        _errorText =
            message.isEmpty ? 'Воркер перезапускается' : 'Воркер: $message';
        notifyListeners();
      case 'worker.restarting':
        _unfinished = true;
        notifyListeners();
    }
  }

  /// Догрузить документ активной страницы, если она готова и не правится.
  void _reloadViewerIfClean(String pageId) {
    if (pageId.isEmpty || pageId != _activeId) return;
    unawaited(viewer.reloadIfClean(pageId));
  }

  void _mergePage(Map<String, dynamic> data) {
    final pageId = '${data['page_id'] ?? ''}';
    if (pageId.isEmpty) return;
    var changed = false;
    _pages = [
      for (final page in _pages)
        if (page.id == pageId)
          () {
            changed = true;
            return page.merge(data);
          }()
        else
          page,
    ];
    if (changed) notifyListeners();
  }

  /// Прогресс прогона: строка всегда «running» (зеркало `onProgress` веба).
  ///
  /// `status` в payload — человекочитаемая стадия пайплайна («Маска букв»,
  /// «Вёрстка»), а не статус страницы: нормализация превращала её в `idle`,
  /// и правка перевода выглядела как «не начата» до конца вёрстки.
  void _mergeProgress(Map<String, dynamic> data) {
    final pageId = '${data['page_id'] ?? ''}';
    if (pageId.isEmpty) return;
    final progress = data['progress'] ?? data['percent'];
    var changed = false;
    _pages = [
      for (final page in _pages)
        if (page.id == pageId)
          () {
            changed = true;
            return page.copyWith(
              status: 'running',
              progress:
                  (progress as num?)?.toInt() ?? page.progress,
              stage: data.containsKey('stage') ? '${data['stage']}' : page.stage,
              error: '',
            );
          }()
        else
          page,
    ];
    if (changed) notifyListeners();
  }

  List<PageRow> _parsePages(Object? raw) {
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) PageRow.fromJson(item.cast<String, dynamic>()),
    ];
  }

  List<RecentEntry> _parseRecent(Object? raw) {
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) RecentEntry.fromJson(item.cast<String, dynamic>()),
    ];
  }

  void _pruneSelection() {
    final ids = {for (final page in _pages) page.id};
    _selected.removeWhere((id) => !ids.contains(id));
    if (_activeId != null && !ids.contains(_activeId)) _activeId = null;
  }

  Future<void> selectPage(String id, {bool toggle = false}) async {
    await viewer.guardOrRun(() async {
      if (toggle) {
        if (!_selected.remove(id)) _selected.add(id);
        _activeId = _selected.contains(id) ? id : null;
      } else {
        _selected
          ..clear()
          ..add(id);
        _activeId = id;
      }
      await viewer.openPage(_activeId);
      notifyListeners();
    });
  }

  void setQuery(String value) {
    _query = value;
    notifyListeners();
  }

  void setProblemsOnly(bool value) {
    _problemsOnly = value;
    notifyListeners();
  }

  /// Режим работы: отбор / ретушь / прогон (влияет на док и сцену).
  void setMode(String value) {
    if (_mode == value) return;
    _mode = value;
    notifyListeners();
  }

  /// Перенести док к верхнему/нижнему краю: локально сразу, затем PUT.
  ///
  /// Настройка некритичная: ошибка запроса не поднимает полосу и не двигает
  /// док обратно — позиция остаётся на текущую сессию.
  Future<void> setDockPosition(bool atTop) async {
    final value = atTop ? 'top' : 'bottom';
    if (_settings['dock_position'] == value) return;
    _settings = {..._settings, 'dock_position': value};
    notifyListeners();
    final api = _api;
    if (api == null) return;
    try {
      await api.putJson('/api/settings', {'dock_position': value});
    } catch (_) {
      // позиция дока не влияет на прогон
    }
  }

  void clearError() {
    if (_errorText == null) return;
    _errorText = null;
    notifyListeners();
  }

  void dismissDirtyClose() {
    if (!_dirtyClose) return;
    _dirtyClose = false;
    notifyListeners();
  }

  /// Запустить действие: снять прошлую ошибку, пометить занятость.
  Future<void> _run(Future<void> Function(IltApi api) action) async {
    final api = _api;
    if (api == null || _busyAction) return;
    _busyAction = true;
    _errorText = null;
    notifyListeners();
    try {
      await action(api);
    } on ApiAuthException catch (error) {
      _errorText = 'Ошибка авторизации: $error';
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
      if (error.statusCode == 409 && _pendingClose) {
        _dirtyClose = true;
      }
    } catch (error) {
      _errorText = 'Не удалось выполнить: $error';
    } finally {
      _pendingClose = false;
      _busyAction = false;
      notifyListeners();
    }
  }

  bool _pendingClose = false;

  /// Импорт выбранных путей: файлы по одному, папка целиком.
  Future<void> importPaths(
    List<String> paths, {
    String chapterMode = 'subdir',
    bool recursive = false,
  }) =>
      viewer.guardOrRun(() => _run((api) async {
            for (final path in paths) {
              await api.postJson('/api/import', {
                'path': path,
                'chapter_mode': chapterMode,
                'recursive': recursive,
              });
            }
            applyBootstrap(await api.getJson('/api/bootstrap'));
          }));

  Future<void> openRecent(String id) =>
      viewer.guardOrRun(() => _run((api) async {
            applyCollection(
              await api.postJson('/api/project/open-recent', {'id': id}),
            );
          }));

  Future<void> clearRecent() => _run((api) async {
        await api.putJson('/api/settings', {'recent_projects': <String>[]});
        _recent = const [];
      });

  /// Запустить перевод: очередь помечается сразу (оптимистичная реакция),
  /// POST уходит следом; при ошибке список откатывается к прежним статусам.
  ///
  /// «Всё» шлётся с `skip_ready` (паритет с вебом): готовые страницы не
  /// переделываются, в очередь встают только неготовые.
  Future<void> translate({String? pageId}) {
    if (_api == null || _busyAction) return Future.value();
    final before = _pages;
    _markQueued(
      pageId == null ? (page) => !page.isReady : (page) => page.id == pageId,
    );
    return _run((api) async {
      try {
        if (pageId == null) {
          await api.postJson('/api/jobs/translate', {
            'scope': 'all',
            'skip_ready': true,
          });
        } else {
          await api.postJson('/api/jobs/translate', {
            'scope': 'page',
            'page_id': pageId,
          });
        }
      } catch (_) {
        _pages = before;
        notifyListeners();
        rethrow;
      }
    });
  }

  Future<void> pause() => _run((api) async {
        final data = await api.postJson('/api/jobs/pause');
        _paused = data['paused'] == true;
      });

  Future<void> resume() => _run((api) async {
        final data = await api.postJson('/api/jobs/resume');
        _paused = data['paused'] == true;
      });

  Future<void> cancelJobs() => _run((api) async {
        final data = await api.postJson('/api/jobs/cancel');
        _paused = data['paused'] == true;
        _unfinished = data['unfinished'] == true;
        _pages = [
          for (final page in _pages)
            if (page.isQueued || page.isRunning)
              page.copyWith(status: 'idle', progress: 0, stage: '', error: '')
            else
              page,
        ];
      });

  Future<void> retryErrors() => _run((api) async {
        await api.postJson('/api/jobs/retry-errors');
        _markQueued((page) => page.isProblem);
      });

  Future<void> removePages(List<String> ids) => _run((api) async {
        applyCollection(
          await api.postJson(
            '/api/project/remove-pages',
            {'page_ids': ids},
          ),
        );
      });

  Future<void> reorderPages(List<String> ids) => _run((api) async {
        applyCollection(
          await api.postJson('/api/project/reorder', {'page_ids': ids}),
        );
      });

  /// Байты серверной миниатюры страницы (`GET /api/pages/{id}/image/thumb`).
  ///
  /// Null — нет API, страница ещё не обработана (404) или сеть недоступна:
  /// строка рельса показывает плейсхолдер.
  Future<Uint8List?> loadThumbnail(String pageId) async {
    final api = _api;
    if (api == null || pageId.isEmpty) return null;
    try {
      return await api.getBytes(
        '/api/pages/${Uri.encodeComponent(pageId)}/image/thumb',
      );
    } catch (_) {
      return null;
    }
  }

  /// Соседняя страница (стрелки/PgUp/PgDn).
  Future<void> stepPage(int delta) async {
    if (_pages.isEmpty) return;
    final index = _pages.indexWhere((page) => page.id == _activeId);
    final next = index < 0 ? 0 : index + delta;
    if (next < 0 || next >= _pages.length) return;
    await selectPage(_pages[next].id);
  }

  /// Следующая проблемная страница (N): ошибка или переполнение.
  Future<void> focusNextProblem() async {
    if (_pages.isEmpty) return;
    final start = _pages.indexWhere((page) => page.id == _activeId);
    for (var offset = 1; offset <= _pages.length; offset++) {
      final index = (math.max(start, 0) + offset) % _pages.length;
      final page = _pages[index];
      if (page.isProblem || page.overflow) {
        await selectPage(page.id);
        return;
      }
    }
  }

  Future<void> closeProject({bool force = false}) =>
      viewer.guardOrRun(() async {
        _pendingClose = true;
        await _run((api) async {
          applyCollection(
            await api.postJson('/api/project/close', {'force': force}),
          );
        });
      });

  /// Сохранить настройки: одним PUT только изменённые ключи.
  Future<void> updateSettings(Map<String, dynamic> patch) => _run((api) async {
        if (patch.isEmpty) {
          clearPreview();
          return;
        }
        final data = await api.putJson('/api/settings', patch);
        final settings = data['settings'];
        if (settings is Map) {
          _settings = settings.cast<String, dynamic>();
        } else {
          _settings = {..._settings, ...patch};
        }
        _preview = null;
        notifyListeners();
      });

  /// Отметить первый запуск пройденным.
  Future<void> completeFirstRun(Map<String, dynamic> patch) =>
      updateSettings({...patch, 'first_run_complete': true});

  Future<void> loadPackage(String path) =>
      viewer.guardOrRun(() => _run((api) async {
            final data = await api
                .postJson('/api/project/package/load', {'path': path});
            if (data['cancelled'] == true) return;
            applyCollection(data);
            final editor = data['editor'];
            if (editor is Map) {
              final pageId = '${editor['active_page_id'] ?? ''}';
              if (pageId.isNotEmpty) {
                await selectPage(pageId);
              }
              final zoom = editor['zoom'] ?? 'fit';
              viewer.session.restoreSession(
                zoom is num ? zoom.toDouble() : '$zoom',
                (editor['scroll_left'] as num?)?.toDouble() ?? 0,
                (editor['scroll_top'] as num?)?.toDouble() ?? 0,
              );
            }
          }));

  Future<void> savePackage(String path) => _run((api) async {
        final transform = viewer.session.transform;
        final data = await api.postJson('/api/project/package/save', {
          'path': path,
          'editor': {
            'active_page_id': viewer.pageId ?? '',
            'zoom': viewer.session.zoomMode,
            'scroll_left': -transform.tx,
            'scroll_top': -transform.ty,
          },
        });
        applyCollection(data);
        _dirtyClose = false;
      });

  /// Обновить состояние паузы после восстановления очереди.
  Future<void> refreshJobs() async {
    final api = _api;
    if (api == null) return;
    try {
      final data = await api.getJson('/api/jobs');
      _paused = data['paused'] == true;
      _unfinished = data['unfinished'] == true;
      notifyListeners();
    } catch (_) {
      // не критично: состояние догонит следующее событие
    }
  }

  void _markQueued(bool Function(PageRow page) test) {
    _pages = [
      for (final page in _pages)
        if (test(page))
          page.copyWith(status: 'queued', progress: 0, stage: '', error: '')
        else
          page,
    ];
    notifyListeners();
  }
}
