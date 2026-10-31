import 'dart:convert';
import 'dart:io';

import 'data_root.dart';

/// Данные handshake сайдкара: адрес локального HTTP и токен сессии.
class ApiReady {
  const ApiReady({required this.port, required this.token});

  final int port;
  final String token;

  /// Базовый адрес локального API.
  Uri get baseUri => Uri.parse('http://127.0.0.1:$port');

  /// Разобрать JSON строку handshake. `null`, если это не он.
  static ApiReady? tryParse(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty || !trimmed.startsWith('{')) return null;
    Object? decoded;
    try {
      decoded = jsonDecode(trimmed);
    } on FormatException {
      return null;
    }
    if (decoded is! Map) return null;
    final port = decoded['port'];
    final token = decoded['token'];
    if (port is! int || port <= 0 || port > 65535) return null;
    if (token is! String || token.isEmpty) return null;
    return ApiReady(port: port, token: token);
  }

  @override
  bool operator ==(Object other) =>
      other is ApiReady && other.port == port && other.token == token;

  @override
  int get hashCode => Object.hash(port, token);

  @override
  String toString() => 'ApiReady(port: $port)';
}

/// Кандидаты пути `api.json` в порядке проверки.
///
/// Сначала явный `ILT_API_JSON`, затем корни данных из [dataRootCandidates].
List<String> apiReadyCandidates({
  Map<String, String>? environment,
  String? executableDir,
  String? repoRoot,
}) {
  final env = environment ?? Platform.environment;
  final paths = <String>[];
  final explicit = (env['ILT_API_JSON'] ?? '').trim();
  if (explicit.isNotEmpty) paths.add(explicit);
  for (final root in dataRootCandidates(
    environment: env,
    executableDir: executableDir,
    repoRoot: repoRoot,
  )) {
    paths.add('$root/api.json');
  }
  return paths;
}

/// Прочитать первый валидный `api.json` из кандидатов (`null`, если нет).
Future<ApiReady?> readApiReadyFromFiles(List<String> candidates) async {
  for (final path in candidates) {
    try {
      final text = await File(path).readAsString();
      final ready = ApiReady.tryParse(text);
      if (ready != null) return ready;
    } on FileSystemException {
      continue;
    }
  }
  return null;
}

/// Удалить устаревшие `api.json` перед запуском своего сайдкара.
void removeStaleApiReady(List<String> candidates) {
  for (final path in candidates) {
    try {
      final file = File(path);
      if (file.existsSync()) file.deleteSync();
    } on FileSystemException {
      continue;
    }
  }
}
