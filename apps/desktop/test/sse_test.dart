import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:ilt_desktop/src/api/errors.dart';
import 'package:ilt_desktop/src/api/sse.dart';

void main() {
  test('парсер собирает кадр и игнорирует keep-alive', () {
    final parser = SseParser();
    expect(parser.addLine('event: job'), isNull);
    expect(parser.addLine('data: {"a": 1}'), isNull);
    final frame = parser.addLine('');
    expect(frame, isNotNull);
    expect(frame!.event, 'job');
    expect(frame.data['a'], 1);
    expect(parser.addLine(': keep-alive'), isNull);
    expect(parser.addLine(''), isNull);
  });

  test('сообщение без event получает имя message', () {
    final parser = SseParser();
    parser.addLine('data: {"n": 2}');
    final frame = parser.addLine('');
    expect(frame?.event, 'message');
    expect(frame?.data['n'], 2);
  });

  test('не-JSON data сохраняется как raw', () {
    final parser = SseParser();
    parser.addLine('event: note');
    parser.addLine('data: просто текст');
    final frame = parser.addLine('');
    expect(frame?.data['raw'], 'просто текст');
  });

  test('sseFrames читает поток ответа', () async {
    final payload = utf8.encode(
      'event: job\ndata: {"n": 1}\n\n: keep-alive\n\n'
      'event: done\ndata: {"n": 2}\n\n',
    );
    final response = http.StreamedResponse(Stream.fromIterable([payload]), 200);
    final frames = await sseFrames(response).toList();
    expect(frames.map((frame) => frame.event).toList(), ['job', 'done']);
    expect(frames.last.data['n'], 2);
  });

  test('EventStream переподключается после ошибки', () async {
    var calls = 0;
    final stream = EventStream(
      connect: () async {
        calls += 1;
        if (calls == 1) throw http.ClientException('boom');
        return http.StreamedResponse(
          Stream.fromIterable([utf8.encode('event: tick\ndata: {}\n\n')]),
          200,
        );
      },
      initialDelay: const Duration(milliseconds: 5),
      maxDelay: const Duration(milliseconds: 10),
    );
    addTearDown(stream.stop);
    final frame = await stream.frames().first;
    expect(frame.event, 'tick');
    expect(calls, greaterThanOrEqualTo(2));
  });

  test('EventStream пробрасывает ApiAuthException', () async {
    final stream = EventStream(
      connect: () async => throw ApiAuthException('нет'),
      initialDelay: const Duration(milliseconds: 5),
    );
    await expectLater(stream.frames(), emitsError(isA<ApiAuthException>()));
  });
}
