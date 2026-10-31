import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/errors.dart';
import '../api/ilt_api.dart';
import '../model/runtime_pack.dart';

/// Файл модели: наличие и текущая загрузка.
class ModelEntry {
  const ModelEntry({
    required this.kind,
    required this.present,
    this.path = '',
    this.bytesDone = 0,
    this.bytesTotal = 0,
    this.error = '',
  });

  final String kind;
  final bool present;
  final String path;
  final int bytesDone;
  final int bytesTotal;
  final String error;

  bool get downloading => !present && bytesDone > 0 && error.isEmpty;

  /// Процент (null, если общий размер неизвестен).
  double? get percent {
    if (bytesTotal <= 0) return null;
    return (bytesDone / bytesTotal).clamp(0.0, 1.0);
  }

  ModelEntry copyWith({
    bool? present,
    int? bytesDone,
    int? bytesTotal,
    String? error,
  }) =>
      ModelEntry(
        kind: kind,
        present: present ?? this.present,
        path: path,
        bytesDone: bytesDone ?? this.bytesDone,
        bytesTotal: bytesTotal ?? this.bytesTotal,
        error: error ?? this.error,
      );
}

/// Устройство, подключённое к LAN-доступу.
class DeviceEntry {
  const DeviceEntry({
    required this.id,
    this.name = '',
    this.address = '',
    this.active = false,
  });

  final String id;
  final String name;
  final String address;
  final bool active;

  factory DeviceEntry.fromJson(Map<String, dynamic> json) => DeviceEntry(
        id: '${json['id'] ?? ''}',
        name: '${json['name'] ?? json['agent'] ?? ''}',
        address: '${json['address'] ?? json['ip'] ?? ''}',
        active: json['active'] == true,
      );
}

/// Снимок состояния удалённого доступа.
class RemoteView {
  const RemoteView({
    this.enabled = false,
    this.addresses = const [],
    this.pairingCode = '',
    this.devices = const [],
    this.clients = 0,
  });

  final bool enabled;
  final List<String> addresses;
  final String pairingCode;
  final List<DeviceEntry> devices;
  final int clients;

  factory RemoteView.fromJson(Map<String, dynamic> json) => RemoteView(
        enabled: json['enabled'] == true,
        addresses: [
          for (final item in (json['addresses'] as List? ?? const []))
            '$item',
        ],
        pairingCode: '${json['pairing_code'] ?? ''}',
        devices: [
          for (final item in (json['devices'] as List? ?? const []))
            if (item is Map) DeviceEntry.fromJson(item.cast<String, dynamic>()),
        ],
        clients: (json['clients'] as num?)?.toInt() ?? 0,
      );
}

/// Строка глоссария: `{source, target, gender, note}`.
class GlossaryRow {
  const GlossaryRow({
    this.source = '',
    this.target = '',
    this.gender = '',
    this.note = '',
  });

  final String source;
  final String target;
  final String gender;
  final String note;

  factory GlossaryRow.fromJson(Map<String, dynamic> json) => GlossaryRow(
        source: '${json['source'] ?? ''}'.trim(),
        target: '${json['target'] ?? ''}',
        gender: '${json['gender'] ?? ''}'.trim(),
        note: '${json['note'] ?? ''}',
      );

  Map<String, dynamic> toJson() => {
        'source': source,
        'target': target,
        'gender': gender,
        'note': note,
      };

  GlossaryRow copyWith({String? source, String? target, String? gender, String? note}) =>
      GlossaryRow(
        source: source ?? this.source,
        target: target ?? this.target,
        gender: gender ?? this.gender,
        note: note ?? this.note,
      );

  bool get isEmpty => source.trim().isEmpty;
}

/// Параметры запуска экспорта.
class ExportOptions {
  const ExportOptions({
    required this.pageIds,
    required this.dest,
    this.format = 'png',
    this.jpegQuality = 90,
    this.conflict = 'rename',
    this.openAfter = false,
    this.content = 'result',
    this.archive = 'folder',
  });

  final List<String> pageIds;
  final String dest;
  final String format;
  final int jpegQuality;
  final String conflict;
  final bool openAfter;
  final String content;
  final String archive;

  Map<String, dynamic> toJson() => {
        'page_ids': pageIds,
        'dest': dest,
        'format': format,
        'jpeg_quality': jpegQuality,
        'conflict': conflict,
        'content': content,
        'archive': archive,
      };

  ExportOptions copyWith({
    List<String>? pageIds,
    String? dest,
    String? format,
    int? jpegQuality,
    String? conflict,
    bool? openAfter,
  }) =>
      ExportOptions(
        pageIds: pageIds ?? this.pageIds,
        dest: dest ?? this.dest,
        format: format ?? this.format,
        jpegQuality: jpegQuality ?? this.jpegQuality,
        conflict: conflict ?? this.conflict,
        openAfter: openAfter ?? this.openAfter,
        content: content,
        archive: archive,
      );
}

/// Итог завершённого экспорта.
class ExportResult {
  const ExportResult({
    required this.saved,
    this.paths = const [],
    this.openAfter = false,
    this.errors = const [],
  });

  final int saved;
  final List<String> paths;
  final bool openAfter;
  final List<String> errors;
}

/// Состояние вторичных экранов: модели, удалёнка, глоссарий, экспорт.
class SecondaryState extends ChangeNotifier {
  IltApi? _api;
  String? _errorText;

  final Map<String, ModelEntry> _models = {};
  RuntimeView _runtime = const RuntimeView();
  RemoteView _remote = const RemoteView();
  List<GlossaryRow> _glossary = const [];
  bool _glossaryLoading = false;
  ExportResult? _lastExport;
  ExportOptions? _lastOptions;
  String? _exportJobId;
  String? _finishedExportJobId;
  static const Duration _exportTimeout = Duration(seconds: 75);

  /// Открыть папку после экспорта (ставит хост; в тестах — запись).
  void Function(String path)? onOpenFolder;

  IltApi? get api => _api;
  Map<String, dynamic> _preparation = const {};
  Map<String, dynamic> _preparationPlan = const {};
  Map<String, dynamic> get preparation => _preparation;
  Map<String, dynamic> get preparationPlan => _preparationPlan;

  Future<void> refreshPreparation() => _guard((api) async {
        final snapshot = await api.getJson('/api/preparation');
        if (_api != api) return;
        _preparation = snapshot;
        if (snapshot['state'] == 'ready' && mapEquals(
            _preparationPlan['selection'] as Map?, snapshot['selection'] as Map?)) {
          _preparationPlan = snapshot;
        }
      });

  Future<void> previewPreparation(Map<String, dynamic> selection) => _guard((api) async {
        _preparationPlan = const {};
        _preparationPlan = await api.postJson('/api/preparation/plan', selection);
      });

  Future<void> startPreparation(Map<String, dynamic> selection) => _guard((api) async {
        _preparation = await api.postJson('/api/preparation/start', selection);
        await refreshPreparation();
      });

  Future<void> verifyPreparation(Map<String, dynamic> selection) => _guard((api) async {
        _preparation = await api.postJson('/api/preparation/verify', selection);
        await refreshPreparation();
      });

  Future<void> pausePreparation() => _guard((api) async {
        _preparation = await api.postJson('/api/preparation/pause');
      });

  Future<void> resumePreparation() => _guard((api) async {
        _preparation = await api.postJson('/api/preparation/resume');
        await refreshPreparation();
      });
  Future<void> changeComponentLocation(String path) => _guard((api) async {
        await api.postJson('/api/preparation/location', {'path': path});
      });

  void applyPreparationProgress(Map<String, dynamic> data) {
    _preparation = data;
    if (data['state'] == 'ready') {
      _preparationPlan = data;
      unawaited(refreshRuntime());
      unawaited(refreshModels());
    }
    notifyListeners();
  }
  String? get errorText => _errorText;
  RuntimeView get runtime => _runtime;
  RemoteView get remote => _remote;
  List<GlossaryRow> get glossary => _glossary;
  bool get glossaryLoading => _glossaryLoading;
  ExportResult? get lastExport => _lastExport;

  ModelEntry model(String kind) =>
      _models[kind] ?? ModelEntry(kind: kind, present: false);

  List<ModelEntry> get models => [
        model('detector'),
        model('lama'),
        model('font'),
      ];

  bool get allModelsPresent => models.every((item) => item.present);

  void bind(IltApi api) {
    _preparation = const {};
    _preparationPlan = const {};
    _api = api;
    _errorText = null;
    _models.clear();
    _runtime = const RuntimeView();
    _remote = const RemoteView();
    _glossary = const [];
    _lastExport = null;
    _lastOptions = null;
    _exportJobId = null;
    _finishedExportJobId = null;
    notifyListeners();
  }

  void detach() {
    _preparation = const {};
    _preparationPlan = const {};
    _api = null;
    _errorText = null;
    _models.clear();
    _runtime = const RuntimeView();
    _remote = const RemoteView();
    _glossary = const [];
    _glossaryLoading = false;
    _lastExport = null;
    _exportJobId = null;
    _finishedExportJobId = null;
    notifyListeners();
  }

  void clearError() {
    if (_errorText == null) return;
    _errorText = null;
    notifyListeners();
  }

  void clearLastExport() {
    if (_lastExport == null) return;
    _lastExport = null;
    notifyListeners();
  }

  /// Выполнить запрос; notify — только асинхронно (экраны зовут из initState).
  Future<void> _guard(Future<void> Function(IltApi api) action) async {
    final api = _api;
    if (api == null) return;
    _errorText = null;
    try {
      await action(api);
    } on ApiAuthException catch (error) {
      _errorText = 'Ошибка авторизации: $error';
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
    } catch (error) {
      _errorText = 'Не удалось выполнить: $error';
    } finally {
      notifyListeners();
    }
  }

  // --- Модели ---

  Future<void> refreshModels() => _guard((api) async {
        final data = await api.getJson('/api/models');
        for (final kind in const ['detector', 'lama', 'font']) {
          final raw = data[kind];
          if (raw is! Map) continue;
          final current = _models[kind];
          _models[kind] = ModelEntry(
            kind: kind,
            present: raw['present'] == true,
            path: '${raw['path'] ?? ''}',
            bytesDone: current?.present == true ? 0 : (current?.bytesDone ?? 0),
            bytesTotal: current?.bytesTotal ?? 0,
          );
        }
      });

  void applyModelProgress(Map<String, dynamic> data) {
    final kind = '${data['kind'] ?? ''}';
    if (kind.isEmpty) return;
    final current = _models[kind] ?? ModelEntry(kind: kind, present: false);
    final done = (data['done_bytes'] ?? data['done'] as num?)?.toInt();
    final total = (data['total_bytes'] ?? data['total'] as num?)?.toInt();
    _models[kind] = current.copyWith(
      bytesDone: done ?? current.bytesDone,
      bytesTotal: total ?? current.bytesTotal,
      error: '',
    );
    notifyListeners();
  }

  /// Запустить скачивание; запрос висит до конца, прогресс идёт событиями.
  void startDownload(String kind) {
    final api = _api;
    if (api == null) return;
    final current = _models[kind] ?? ModelEntry(kind: kind, present: false);
    if (current.downloading) return;
    // Мгновенный отклик: бар появляется сразу, кнопка пропадает до конца.
    _models[kind] = current.copyWith(
      bytesDone: current.bytesDone > 0 ? current.bytesDone : 1,
      error: '',
    );
    notifyListeners();
    unawaited(
      api.postJson('/api/models/download', {'kind': kind}).then((_) {
        _models[kind] = ModelEntry(kind: kind, present: true);
        notifyListeners();
      }).catchError((Object error) {
        final latest = _models[kind] ?? ModelEntry(kind: kind, present: false);
        final message =
            error is ApiException ? apiErrorMessage(error) : '$error';
        _models[kind] = latest.copyWith(error: message);
        notifyListeners();
      }),
    );
  }

  // --- Компоненты рантайма (torch/Argos) ---

  Future<void> refreshRuntime() => _guard((api) async {
        _runtime = RuntimeView.fromJson(await api.getJson('/api/runtime'));
      });

  /// SSE `runtime.progress`: обновить строку пака без полного refresh.
  void applyRuntimeProgress(Map<String, dynamic> data) {
    final id = '${data['id'] ?? ''}';
    if (id.isEmpty) return;
    final state = '${data['state'] ?? ''}';
    final done = (data['done'] as num?)?.toInt() ?? 0;
    final total = (data['total'] as num?)?.toInt() ?? 0;
    final error = '${data['error'] ?? ''}';
    final updated = [
      for (final pack in _runtime.packs)
        if (pack.id == id)
          pack.copyWith(state: state, done: done, total: total, error: error)
        else
          pack,
    ];
    _runtime = _runtime.copyWith(packs: updated);
    notifyListeners();
  }

  /// Поставить установку пака в фон. Идёт один пак за раз.
  void startRuntimeDownload(String id) {
    final api = _api;
    if (api == null) return;
    _patchRuntimePack(id, (pack) => pack.copyWith(state: 'downloading', error: ''));
    unawaited(
      api.postJson('/api/runtime/download', {'id': id}).then((data) {
        if (data['installed'] == true) {
          _patchRuntimePack(id, (pack) => pack.copyWith(state: 'installed'));
        }
      }).catchError((Object error) {
        _patchRuntimePack(id, (pack) => pack.copyWith(state: 'error', error: '$error'));
      }),
    );
  }

  Future<void> removeRuntimePack(String id) => _guard((api) async {
        await api.postJson('/api/runtime/remove', {'id': id});
        _patchRuntimePack(
          id,
          (pack) => pack.copyWith(state: 'available', done: 0, total: 0, error: ''),
        );
      });

  void _patchRuntimePack(
    String id,
    RuntimePack Function(RuntimePack pack) patch,
  ) {
    final updated = [
      for (final pack in _runtime.packs) if (pack.id == id) patch(pack) else pack,
    ];
    _runtime = _runtime.copyWith(packs: updated);
    notifyListeners();
  }

  // --- Удалённый доступ ---

  Future<void> refreshRemote() => _guard((api) async {
        _remote = RemoteView.fromJson(await api.getJson('/api/remote/status'));
      });

  Future<void> issuePairCode() => _guard((api) async {
        _remote = RemoteView.fromJson(await api.postJson('/api/remote/pair-code'));
      });

  Future<void> revokeDevice(String id) => _guard((api) async {
        _remote = RemoteView.fromJson(
          await api.postJson('/api/remote/revoke', {'id': id}),
        );
      });

  // --- Глоссарий ---

  Future<void> loadGlossary() async {
    _glossaryLoading = true;
    await _guard((api) async {
      final data = await api.getJson('/api/project/glossary');
      final raw = data['glossary'];
      _glossary = [
        for (final item in (raw is List ? raw : const []))
          if (item is Map) GlossaryRow.fromJson(item.cast<String, dynamic>()),
      ];
    });
    _glossaryLoading = false;
    notifyListeners();
  }

  Future<void> saveGlossary(List<GlossaryRow> rows) => _guard((api) async {
        final clean = [for (final row in rows) if (!row.isEmpty) row];
        final data = await api.putJson('/api/project/glossary', {
          'glossary': [for (final row in clean) row.toJson()],
        });
        final raw = data['glossary'];
        _glossary = [
          for (final item in (raw is List ? raw : const []))
            if (item is Map) GlossaryRow.fromJson(item.cast<String, dynamic>()),
        ];
      });

  // --- Экспорт ---

  /// Запомнить выбранную хостом папку экспорта (`export_dir` на сервере).
  Future<bool> registerExportFolder(String path) async {
    var ok = false;
    await _guard((api) async {
      await api.postJson('/api/dialog/directory', {'path': path});
      ok = true;
    });
    return ok;
  }

  /// Запустить экспорт и дождаться терминального статуса своего задания.
  ///
  /// Опрос `/api/jobs/status` переживает обрыв SSE: событие могло потеряться,
  /// а задание осталось в очереди сервера.
  Future<bool> runExport(ExportOptions options) async {
    final api = _api;
    if (api == null) return false;
    _lastOptions = options;
    _errorText = null;
    String? jobId;
    try {
      final data = await api.postJson('/api/jobs/export', options.toJson());
      jobId = '${data['job_id'] ?? ''}'.trim();
      if (jobId.isEmpty) {
        throw StateError('Сервер не вернул идентификатор задания');
      }
      _exportJobId = jobId;
      notifyListeners();
      final deadline = DateTime.now().add(_exportTimeout);
      while (true) {
        final current = _api;
        if (current == null || _exportJobId != jobId) {
          throw StateError('Соединение с сайдкаром потеряно');
        }
        final snapshot =
            await current.getJson('/api/jobs/status?job_id=$jobId');
        final status = '${snapshot['status'] ?? ''}';
        final raw = snapshot['result'];
        final result =
            raw is Map ? raw.cast<String, dynamic>() : <String, dynamic>{};
        if (status == 'done') {
          applyJobFinished({
            'kind': 'export',
            'job_id': jobId,
            ...result,
          });
          return true;
        }
        if (status == 'error' || status == 'cancelled') {
          final message = '${result['error'] ?? ''}'.trim();
          throw StateError(message.isNotEmpty
              ? message
              : (status == 'cancelled'
                  ? 'Экспорт отменён'
                  : 'Экспорт завершился с ошибкой'));
        }
        if (DateTime.now().isAfter(deadline)) {
          try {
            await current.postJson('/api/jobs/cancel', {'job_id': jobId});
          } catch (_) {
            // Отмена не должна скрывать исходную ошибку ожидания.
          }
          throw StateError(
            'Результат не дождался за ${_exportTimeout.inSeconds} секунд, '
            'экспорт отменён.',
          );
        }
        await Future<void>.delayed(const Duration(milliseconds: 250));
      }
    } on ApiAuthException catch (error) {
      _errorText = 'Ошибка авторизации: $error';
    } on ApiException catch (error) {
      _errorText = apiErrorMessage(error);
    } catch (error) {
      _errorText = '$error';
    } finally {
      if (_exportJobId == jobId) _exportJobId = null;
      notifyListeners();
    }
    return false;
  }

  /// `job.finished` с результатом экспорта: сохранить итог и открыть папку.
  void applyJobFinished(Map<String, dynamic> data) {
    if ('${data['kind'] ?? ''}' != 'export' && data['saved'] == null) return;
    final jobId = '${data['job_id'] ?? ''}'.trim();
    if (jobId.isNotEmpty) {
      if (jobId == _finishedExportJobId) return;
      _finishedExportJobId = jobId;
    }
    final options = _lastOptions;
    final paths = [
      for (final item in (data['paths'] as List? ?? const [])) '$item',
    ];
    final result = ExportResult(
      saved: (data['saved'] as num?)?.toInt() ?? paths.length,
      paths: paths,
      openAfter: options?.openAfter == true,
      errors: [
        for (final item in (data['errors'] as List? ?? const [])) '$item',
      ],
    );
    _lastExport = result;
    notifyListeners();
    final folder = options?.dest;
    if (result.openAfter && folder != null && folder.isNotEmpty) {
      onOpenFolder?.call(folder);
    }
  }

  /// `job.failed`: ошибка ожидаемого экспорта остаётся в диалоге.
  void applyJobFailed(Map<String, dynamic> data) {
    if ('${data['kind'] ?? ''}' != 'export') return;
    final jobId = '${data['job_id'] ?? ''}'.trim();
    if (_exportJobId != null && jobId.isNotEmpty && jobId != _exportJobId) {
      return;
    }
    final message = '${data['error'] ?? data['message'] ?? ''}'.trim();
    _errorText = message.isEmpty ? 'Экспорт завершился с ошибкой' : message;
    notifyListeners();
  }
}
