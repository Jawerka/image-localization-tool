import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'errors.dart';

/// Кадр SSE: имя события и JSON-данные.
class SseFrame {
  const SseFrame({required this.event, required this.data});

  final String event;
  final Map<String, dynamic> data;

  @override
  String toString() => 'SseFrame($event)';
}

/// Инкрементальный парсер потока SSE.
///
/// Сервер (`_stream_events`) шлёт `event: <type>\ndata: <json>\n\n` и
/// `: keep-alive\n\n` каждые 15 секунд.
class SseParser {
  String _event = '';
  final List<String> _data = [];

  /// Скормить одну строку. Кадр возвращается на пустой строке.
  SseFrame? addLine(String line) {
    if (line.isEmpty) return _dispatch();
    if (line.startsWith(':')) return null;
    final colon = line.indexOf(':');
    final field = colon < 0 ? line : line.substring(0, colon);
    var value = colon < 0 ? '' : line.substring(colon + 1);
    if (value.startsWith(' ')) value = value.substring(1);
    if (field == 'event') {
      _event = value;
    } else if (field == 'data') {
      _data.add(value);
    }
    return null;
  }

  SseFrame? _dispatch() {
    if (_data.isEmpty && _event.isEmpty) return null;
    final text = _data.join('\n');
    final event = _event.isEmpty ? 'message' : _event;
    _data.clear();
    _event = '';
    Object? decoded;
    try {
      decoded = jsonDecode(text);
    } on FormatException {
      decoded = null;
    }
    final data = decoded is Map
        ? decoded.cast<String, dynamic>()
        : <String, dynamic>{'raw': text};
    return SseFrame(event: event, data: data);
  }
}

/// Прочитать поток кадров из ответа `/api/events`.
Stream<SseFrame> sseFrames(http.StreamedResponse response) {
  final parser = SseParser();
  return response.stream
      .transform(utf8.decoder)
      .transform(const LineSplitter())
      .map(parser.addLine)
      .where((frame) => frame != null)
      .cast<SseFrame>();
}

/// Поток событий с самопереподключением и ограниченной выдержкой.
class EventStream {
  EventStream({
    required this.connect,
    this.initialDelay = const Duration(seconds: 1),
    this.maxDelay = const Duration(seconds: 15),
  });

  /// Открыть соединение `/api/events` (бросает при не-200).
  final Future<http.StreamedResponse> Function() connect;
  final Duration initialDelay;
  final Duration maxDelay;

  bool _stopped = false;

  Stream<SseFrame> frames() async* {
    var delay = initialDelay;
    while (!_stopped) {
      try {
        final response = await connect();
        await for (final frame in sseFrames(response)) {
          delay = initialDelay;
          yield frame;
        }
      } on ApiAuthException {
        rethrow;
      } catch (_) {
        // Соединение упало — ждём и пробуем снова.
      }
      if (_stopped) break;
      await Future<void>.delayed(delay);
      delay = delay * 2 > maxDelay ? maxDelay : delay * 2;
    }
  }

  void stop() {
    _stopped = true;
  }
}
