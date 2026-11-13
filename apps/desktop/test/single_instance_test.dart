import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/sidecar/single_instance.dart';

void main() {
  test('quick флаг не становится путём', () {
    final launch = LaunchRequest.fromArgs([
      '--quick',
      r'C:\страница 1.png',
      r'C:\two.jpg',
    ]);
    expect(launch.mode, 'quick');
    expect(launch.paths, [r'C:\страница 1.png', r'C:\two.jpg']);
  });

  test('IPC сохраняет mode quick и несколько путей', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-quick-ipc');
    addTearDown(() => dir.deleteSync(recursive: true));
    final env = {'ILT_DATA_DIR': dir.path};
    final first = SingleInstance(environment: env, executableDir: dir.path);
    final received = Completer<LaunchRequest>();
    await first.acquire(onLaunch: received.complete);
    addTearDown(first.dispose);
    final second = SingleInstance(environment: env, executableDir: dir.path);
    expect(
      await second.forwardIfRunning([
        '--quick',
        r'C:\страница 1.png',
        r'C:\two.jpg',
      ]),
      isTrue,
    );
    final launch = await received.future.timeout(const Duration(seconds: 2));
    expect(launch.mode, 'quick');
    expect(launch.paths, [r'C:\страница 1.png', r'C:\two.jpg']);
  });

  test('acquire пишет instance.json и принимает пути', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-instance');
    addTearDown(() => dir.deleteSync(recursive: true));
    final env = {'ILT_DATA_DIR': dir.path};
    final first = SingleInstance(environment: env, executableDir: dir.path);
    final received = <List<String>>[];
    final gotPaths = Completer<void>();
    await first.acquire(
      onPaths: (paths) {
        received.add(paths);
        if (!gotPaths.isCompleted) gotPaths.complete();
      },
    );
    addTearDown(first.dispose);
    final record = jsonDecode(
      File('${dir.path}/instance.json').readAsStringSync(),
    );
    expect(record['port'], isA<int>());

    final second = SingleInstance(environment: env, executableDir: dir.path);
    expect(await second.forwardIfRunning([r'C:\page.png']), isTrue);
    await gotPaths.future.timeout(const Duration(seconds: 2));
    expect(received.single, [r'C:\page.png']);
  });

  test('закрытый порт → forward false', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-instance-dead');
    addTearDown(() => dir.deleteSync(recursive: true));
    final probe = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final deadPort = probe.port;
    await probe.close();
    File(
      '${dir.path}/instance.json',
    ).writeAsStringSync('{"pid": 999999937, "port": $deadPort}');
    final second = SingleInstance(
      environment: {'ILT_DATA_DIR': dir.path},
      executableDir: dir.path,
    );
    expect(await second.forwardIfRunning([]), isFalse);
  });

  test('без записи instance.json → forward false', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-instance-none');
    addTearDown(() => dir.deleteSync(recursive: true));
    final second = SingleInstance(
      environment: {'ILT_DATA_DIR': dir.path},
      executableDir: dir.path,
    );
    expect(await second.forwardIfRunning([]), isFalse);
  });

  test('недоступный каталог данных → FileSystemException', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-instance-blocked');
    addTearDown(() => dir.deleteSync(recursive: true));
    final blocked = File('${dir.path}/data')..writeAsStringSync('not a dir');
    final single = SingleInstance(
      environment: {'ILT_DATA_DIR': blocked.path},
      executableDir: dir.path,
    );
    addTearDown(single.dispose);
    await expectLater(
      single.acquire(onPaths: (_) {}),
      throwsA(isA<FileSystemException>()),
    );
  });
}
