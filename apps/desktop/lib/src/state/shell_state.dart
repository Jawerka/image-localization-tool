import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';

import '../api/errors.dart';
import '../api/ilt_api.dart';
import '../api/sse.dart';
import '../sidecar/handshake.dart';
import '../sidecar/sidecar_controller.dart';
import 'secondary_state.dart';
import 'workspace_state.dart';

/// Состояние хоста: сайдкар, соединение и данные bootstrap.
enum HostStatus { starting, ready, error }

/// Полноэкранные оверлеи и модалки поверх оболочки.
enum OverlayKind { settings, glossary, remote, export, hotkeys }

/// ChangeNotifier-состояние оболочки (план: без сторонних пакетов стейта).
class ShellState extends ChangeNotifier {
  ShellState({
    required SidecarController sidecar,
    IltApi Function(ApiReady ready)? apiFactory,
  }) : this._(sidecar, apiFactory ?? ((ready) => IltApi(ready: ready)));

  ShellState._(this._sidecar, this._apiFactory) {
    workspace.addListener(_onWorkspaceChanged);
    secondary.addListener(notifyListeners);
  }

  final SidecarController _sidecar;
  final IltApi Function(ApiReady ready) _apiFactory;

  /// Данные главного окна: проект, страницы, недавние, batch.
  final WorkspaceState workspace = WorkspaceState();

  /// Вторичные экраны: модели, удалёнка, глоссарий, экспорт.
  final SecondaryState secondary = SecondaryState();

  HostStatus _status = HostStatus.starting;
  ApiReady? _ready;
  IltApi? _api;
  Map<String, dynamic>? _bootstrap;
  String? _errorMessage;
  bool _authError = false;
  String? _lastEvent;
  int _eventCount = 0;
  EventStream? _events;
  StreamSubscription<SseFrame>? _eventsSub;
  int _run = 0;

  OverlayKind? _overlay;
  bool _firstRunDismissed = false;
  String? _workerFailure;
  Completer<ui.AppExitResponse>? _exit;
  bool _exitWaiting = false;
  bool _hasApiKey = false;

  HostStatus get status => _status;
  ApiReady? get ready => _ready;
  IltApi? get api => _api;
  Map<String, dynamic>? get bootstrap => _bootstrap;
  String? get errorMessage => _errorMessage;
  bool get authError => _authError;
  String? get lastEvent => _lastEvent;
  int get eventCount => _eventCount;

  /// Масштаб интерфейса (учитывает черновик настроек).
  double get uiScale => workspace.uiScale;

  /// Тема: dark / light / system (учитывает черновик настроек).
  String get themeName => workspace.themeName;

  String get sourceLang => workspace.sourceLang;
  String get targetLang => workspace.targetLang;

  /// Задан ли ключ API (значение не показываем).
  bool get hasApiKey => _hasApiKey;

  /// Ключ API сохранён в диспетчере учётных данных.
  void markApiKeySet() {
    _hasApiKey = true;
    notifyListeners();
  }

  /// Папка моделей: из настроек или рядом с файлами данных.
  String get modelsDir {
    final configured = '${workspace.effective('models_dir') ?? ''}'.trim();
    if (configured.isNotEmpty) return configured;
    final detector = secondary.model('detector').path;
    if (detector.isNotEmpty) {
      final parts = detector.split(RegExp(r'[\\/]'));
      if (parts.length > 1) {
        return parts.sublist(0, parts.length - 1).join('\\');
      }
    }
    return dataDir ?? '';
  }

  /// Путь журнала приложения (для «Открыть лог»).
  String? get logPath {
    final paths = _bootstrap?['paths'];
    final data = paths is Map ? '${paths['data'] ?? ''}' : '';
    if (data.isEmpty) return null;
    return '$data/logs/app.log';
  }

  /// Каталог данных (для «Открыть папку данных»).
  String? get dataDir {
    final paths = _bootstrap?['paths'];
    final data = paths is Map ? '${paths['data'] ?? ''}' : '';
    return data.isEmpty ? null : data;
  }

  // --- Оверлеи ---

  OverlayKind? get overlay => _overlay;
  bool get overlayOpen => _overlay != null;

  void openOverlay(OverlayKind kind) {
    if (_overlay == kind) return;
    _overlay = kind;
    notifyListeners();
  }

  void closeOverlay() {
    if (_overlay == null) return;
    _overlay = null;
    workspace.clearPreview();
    notifyListeners();
  }

  /// Мастер первого запуска: показывается один раз до завершения/пропуска.
  bool get showFirstRun =>
      _status == HostStatus.ready &&
      !_firstRunDismissed &&
      _bootstrap != null &&
      !workspace.firstRunComplete;

  void dismissFirstRun() {
    _firstRunDismissed = true;
    notifyListeners();
  }

  // --- Ошибка воркера ---

  String? get workerFailure => _workerFailure;

  void dismissWorkerFailure() {
    if (_workerFailure == null) return;
    _workerFailure = null;
    notifyListeners();
  }

  // --- Выход с незавершённым прогоном ---

  bool get exitPrompt => _exit != null;
  bool get exitWaiting => _exitWaiting;

  /// Запрос выхода: без незаконченных страниц выходим сразу, иначе — диалог.
  ///
  /// Перед выходом ждём запись слоёв, иначе последний выбор может потеряться.
  Future<ui.AppExitResponse> confirmExit() async {
    if (!workspace.busy) {
      await workspace.whenLayersSaved();
      return ui.AppExitResponse.exit;
    }
    final pending = _exit ??= Completer<ui.AppExitResponse>();
    notifyListeners();
    final response = await pending.future;
    if (response == ui.AppExitResponse.exit) {
      await workspace.whenLayersSaved();
    }
    return response;
  }

  void cancelExit() => _resolveExit(ui.AppExitResponse.cancel);

  void exitNow() => _resolveExit(ui.AppExitResponse.exit);

  /// Дождаться конца прогона и выйти автоматически.
  void waitForBatchAndExit() {
    if (_exit == null) return;
    _exitWaiting = true;
    notifyListeners();
    _maybeFinishWaitingExit();
  }

  void _maybeFinishWaitingExit() {
    if (_exitWaiting && _exit != null && !workspace.busy) {
      _resolveExit(ui.AppExitResponse.exit);
    }
  }

  void _resolveExit(ui.AppExitResponse value) {
    final completer = _exit;
    _exit = null;
    _exitWaiting = false;
    notifyListeners();
    completer?.complete(value);
  }

  void _onWorkspaceChanged() {
    _maybeFinishWaitingExit();
    notifyListeners();
  }

  /// Запуск: поднять сайдкар, прочитать bootstrap, подписаться на события.
  Future<void> start() async {
    final run = ++_run;
    _status = HostStatus.starting;
    _errorMessage = null;
    _authError = false;
    _workerFailure = null;
    _firstRunDismissed = false;
    workspace.detach();
    secondary.detach();
    notifyListeners();
    try {
      final ready = await _sidecar.start();
      final api = _apiFactory(ready);
      final bootstrap = await api.getJson('/api/bootstrap');
      _ready = ready;
      _api = api;
      _bootstrap = bootstrap;
      _hasApiKey = bootstrap['has_api_key'] == true;
      _status = HostStatus.ready;
      workspace.bind(api);
      workspace.applyBootstrap(bootstrap);
      secondary.bind(api);
      unawaited(workspace.refreshJobs());
      _listenEvents(api);
      _watchExit(run);
    } on ApiAuthException catch (error) {
      _authError = true;
      _fail('Ошибка авторизации: $error');
    } on SidecarStartException catch (error) {
      _fail(error.message);
    } catch (error) {
      _fail('Не удалось подключиться: $error');
    }
    notifyListeners();
  }

  /// Перезапуск после ошибки: остановить сайдкар и начать заново.
  Future<void> retry() async {
    _run += 1;
    await _stopEvents();
    _api?.close();
    _api = null;
    _sidecar.stop();
    await start();
  }

  /// Перезапуск по требованию (например, после смены настроек сети).
  Future<void> restartSidecar() => retry();

  /// US1#3: смерть процесса в рантайме → error + Retry, а не только
  /// бесконечный SSE-реконнект. Свой прогон сверяется по номеру `run`.
  void _watchExit(int run) {
    final exit = _sidecar.processExitCode;
    if (exit == null) return;
    unawaited(exit.then((code) {
      if (_run != run || _status != HostStatus.ready) return;
      unawaited(_stopEvents());
      _fail('Сайдкар завершился неожиданно (код $code)');
      notifyListeners();
    }));
  }

  void _listenEvents(IltApi api) {
    _events = EventStream(connect: api.openEvents, onConnected: () async {
      await secondary.refreshPreparation();
      await secondary.refreshRuntime();
    });
    _eventsSub = _events!.frames().listen(
      (frame) {
        _lastEvent = frame.event;
        _eventCount += 1;
        // Сервер шлёт конверт `{"type": ..., "payload": {...}}`; в состояние
        // передаём только payload, иначе поля вроде page_id не находятся.
        final raw = frame.data['payload'];
        final payload =
            raw is Map ? raw.cast<String, dynamic>() : frame.data;
        workspace.applyEvent(frame.event, payload);
        switch (frame.event) {
          case 'model.progress':
            secondary.applyModelProgress(payload);
          case 'runtime.progress':
            secondary.applyRuntimeProgress(payload);
          case 'preparation.progress':
            secondary.applyPreparationProgress(payload);
          case 'job.finished':
            secondary.applyJobFinished(payload);
          case 'job.failed':
            secondary.applyJobFailed(payload);
          case 'worker.failed':
            final message =
                '${payload['message'] ?? payload['error'] ?? payload['reason'] ?? ''}'
                    .trim();
            _workerFailure = message.isEmpty
                ? 'Воркер перезапускался слишком часто и остановлен.'
                : message;
        }
        notifyListeners();
      },
      onError: (Object error) {
        if (error is ApiAuthException) {
          _authError = true;
          _fail('Ошибка авторизации: $error');
        }
        notifyListeners();
      },
    );
  }

  Future<void> _stopEvents() async {
    _events?.stop();
    _events = null;
    final subscription = _eventsSub;
    _eventsSub = null;
    await subscription?.cancel();
  }

  void _fail(String message) {
    _status = HostStatus.error;
    _errorMessage = message;
  }

  @override
  void dispose() {
    _run += 1;
    workspace.removeListener(_onWorkspaceChanged);
    secondary.removeListener(notifyListeners);
    unawaited(_stopEvents());
    _api?.close();
    _sidecar.stop();
    super.dispose();
  }
}
