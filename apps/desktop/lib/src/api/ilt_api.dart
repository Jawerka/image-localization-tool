import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../sidecar/handshake.dart';
import 'errors.dart';

/// Бинарный ответ (превью региона) с заголовками сервера.
class ApiBytes {
  const ApiBytes({required this.bytes, required this.headers});

  final Uint8List bytes;
  final Map<String, String> headers;
}

/// Клиент локального API с cookie-токеном сессии.
class IltApi {
  IltApi({required this.ready, http.Client? client})
      : _client = client ?? http.Client();

  final ApiReady ready;
  final http.Client _client;

  Map<String, String> _headers({bool json = false}) => {
        'Cookie': 'ilt_session=${ready.token}',
        'Accept': 'application/json',
        if (json) 'Content-Type': 'application/json',
      };

  /// GET JSON. 401 — [ApiAuthException], прочие >= 400 — [ApiException].
  Future<Map<String, dynamic>> getJson(String path) => _request('GET', path);

  /// POST JSON с телом.
  Future<Map<String, dynamic>> postJson(
    String path, [
    Map<String, dynamic>? body,
  ]) =>
      _request('POST', path, body);

  /// PUT JSON с телом.
  Future<Map<String, dynamic>> putJson(
    String path, [
    Map<String, dynamic>? body,
  ]) =>
      _request('PUT', path, body);

  Future<Map<String, dynamic>> _request(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final request = http.Request(method, ready.baseUri.resolve(path));
    request.headers.addAll(_headers(json: body != null));
    if (body != null) request.body = jsonEncode(body);
    final response = await _client.send(request);
    final text = await response.stream.bytesToString();
    if (response.statusCode == 401) {
      throw ApiAuthException('Не авторизован');
    }
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, text);
    }
    if (text.trim().isEmpty) return <String, dynamic>{};
    final decoded = jsonDecode(text);
    if (decoded is! Map) {
      throw ApiException(response.statusCode, 'Ожидался JSON-объект');
    }
    return decoded.cast<String, dynamic>();
  }

  /// GET байтов (изображения страниц).
  Future<Uint8List> getBytes(String path) async {
    final request = http.Request('GET', ready.baseUri.resolve(path));
    request.headers.addAll(_headers());
    final response = await _client.send(request);
    final bytes = await response.stream.toBytes();
    if (response.statusCode == 401) {
      throw ApiAuthException('Не авторизован');
    }
    if (response.statusCode >= 400) {
      throw ApiException(
        response.statusCode,
        utf8.decode(bytes, allowMalformed: true),
      );
    }
    return bytes;
  }

  /// POST с бинарным ответом (превью региона стиля).
  Future<ApiBytes> postBytes(String path, [Map<String, dynamic>? body]) async {
    final request = http.Request('POST', ready.baseUri.resolve(path));
    request.headers.addAll(_headers(json: body != null));
    if (body != null) request.body = jsonEncode(body);
    final response = await _client.send(request);
    final bytes = await response.stream.toBytes();
    if (response.statusCode == 401) {
      throw ApiAuthException('Не авторизован');
    }
    if (response.statusCode >= 400) {
      throw ApiException(
        response.statusCode,
        utf8.decode(bytes, allowMalformed: true),
      );
    }
    return ApiBytes(bytes: bytes, headers: response.headers);
  }

  /// Открыть поток `/api/events` (статус проверяется до чтения кадров).
  Future<http.StreamedResponse> openEvents() async {
    final request = http.Request('GET', ready.baseUri.resolve('/api/events'));
    request.headers.addAll(_headers());
    final response = await _client.send(request);
    if (response.statusCode == 401) {
      throw ApiAuthException('Не авторизован');
    }
    if (response.statusCode != 200) {
      throw ApiException(response.statusCode, 'SSE ${response.statusCode}');
    }
    return response;
  }

  void close() => _client.close();
}
