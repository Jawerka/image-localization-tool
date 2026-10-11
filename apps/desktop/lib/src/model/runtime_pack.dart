/// Компоненты рантайма: пак (torch/Argos) и снимок железа из `/api/runtime`.
class RuntimePack {
  const RuntimePack({
    required this.id,
    this.title = '',
    this.kind = '',
    this.version = '',
    this.sizeBytes = 0,
    this.installedBytes = 0,
    this.state = 'available',
    this.recommended = false,
    this.error = '',
    this.done = 0,
    this.total = 0,
    this.format = '',
    this.source = '',
  });

  final String id;
  final String title;
  final String kind;
  final String version;
  final int sizeBytes;
  final int installedBytes;
  final String state;
  final bool recommended;
  final String error;
  final int done;
  final int total;
  final String format;
  final String source;

  bool get installed => state == 'installed';
  bool get downloading => state == 'downloading' || state == 'installing';
  bool get failed => state == 'error' || error.isNotEmpty;

  /// Процент (null, если общий размер неизвестен).
  double? get percent {
    if (total <= 0) return null;
    return (done / total).clamp(0.0, 1.0);
  }

  factory RuntimePack.fromJson(Map<String, dynamic> json) => RuntimePack(
        id: '${json['id'] ?? ''}',
        title: '${json['title'] ?? json['id'] ?? ''}',
        kind: '${json['kind'] ?? ''}',
        version: '${json['version'] ?? ''}',
        sizeBytes: (json['size_bytes'] as num?)?.toInt() ?? 0,
        installedBytes: (json['installed_bytes'] as num?)?.toInt() ?? 0,
        state: '${json['state'] ?? 'available'}',
        recommended: json['recommended'] == true,
        error: '${json['error'] ?? ''}',
        format: '${json['format'] ?? ''}',
        source: '${json['source'] ?? ''}',
      );

  RuntimePack copyWith({String? state, int? done, int? total, String? error}) =>
      RuntimePack(
        id: id,
        title: title,
        kind: kind,
        version: version,
        sizeBytes: sizeBytes,
        installedBytes: installedBytes,
        state: state ?? this.state,
        recommended: recommended,
        error: error ?? this.error,
        done: done ?? this.done,
        total: total ?? this.total,
        format: format,
        source: source,
      );
}

/// Снимок `/api/runtime`: паки, железо, готовность torch/Argos.
class RuntimeView {
  const RuntimeView({
    this.packs = const [],
    this.vendor = '',
    this.gpuName = '',
    this.driver,
    this.recommended = '',
    this.reason = '',
    this.torchReady = false,
    this.argosReady = false,
    this.deviceEffective = 'cpu',
    this.downloadId = '',
    this.downloadState = 'idle',
  });

  final List<RuntimePack> packs;
  final String vendor;
  final String gpuName;
  final int? driver;
  final String recommended;
  final String reason;
  final bool torchReady;
  final bool argosReady;
  final String deviceEffective;
  final String downloadId;
  final String downloadState;

  RuntimePack? pack(String id) {
    for (final item in packs) {
      if (item.id == id) return item;
    }
    return null;
  }

  factory RuntimeView.fromJson(Map<String, dynamic> json) {
    final hardware =
        (json['hardware'] as Map?)?.cast<String, dynamic>() ?? const {};
    final download =
        (json['download'] as Map?)?.cast<String, dynamic>() ?? const {};
    return RuntimeView(
      packs: [
        for (final item in (json['packs'] as List? ?? const []))
          if (item is Map) RuntimePack.fromJson(item.cast<String, dynamic>()),
      ],
      vendor: '${hardware['vendor'] ?? ''}',
      gpuName: '${hardware['name'] ?? ''}',
      driver: (hardware['driver'] as num?)?.toInt(),
      recommended: '${hardware['recommended'] ?? ''}',
      reason: '${hardware['reason'] ?? ''}',
      torchReady: json['torch_ready'] == true,
      argosReady: json['argos_ready'] == true,
      deviceEffective: '${json['device_effective'] ?? 'cpu'}',
      downloadId: '${download['id'] ?? ''}',
      downloadState: '${download['state'] ?? 'idle'}',
    );
  }

  RuntimeView copyWith({List<RuntimePack>? packs}) => RuntimeView(
        packs: packs ?? this.packs,
        vendor: vendor,
        gpuName: gpuName,
        driver: driver,
        recommended: recommended,
        reason: reason,
        torchReady: torchReady,
        argosReady: argosReady,
        deviceEffective: deviceEffective,
        downloadId: downloadId,
        downloadState: downloadState,
      );
}
