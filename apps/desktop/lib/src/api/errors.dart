// Ошибки локального API сайдкара.

import 'dart:convert';

/// 401: токен отсутствует или неверен (переподключение не поможет).
class ApiAuthException implements Exception {
  ApiAuthException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Прочий ошибочный ответ API (>= 400, кроме 401).
class ApiException implements Exception {
  ApiException(this.statusCode, this.body);

  final int statusCode;
  final String body;

  @override
  String toString() => 'API $statusCode: $body';
}

/// Человекочитаемое сообщение из ошибки API (`{"error": "..."}` или сырой текст).
String apiErrorMessage(ApiException error) {
  final body = error.body.trim();
  final start = body.indexOf('{');
  if (start >= 0) {
    try {
      final decoded = jsonDecode(body.substring(start));
      if (decoded is Map && decoded['error'] is String) {
        return decoded['error'] as String;
      }
    } catch (_) {
      // не JSON — показываем сырой текст ниже
    }
  }
  return body.isEmpty ? 'API ${error.statusCode}' : body;
}
