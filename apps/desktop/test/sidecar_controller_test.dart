import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:ilt_desktop/src/sidecar/sidecar_controller.dart';
import 'package:ilt_desktop/src/sidecar/sidecar_process.dart';

/// Подставной процесс сайдкара без реального запуска.
class _FakeProcess implements SidecarProcess {
  final stdout = StreamController<String>.broadcast();
  final stderr = StreamController<String>.broadcast();
  final exit = Completer<int>();
  bool killed = false;

  @override
  Stream<String> get stdoutLines => stdout.stream;

  @override
  Stream<String> get stderrLines => stderr.stream;

  @override
  Future<int> get exitCode => exit.future;

  @override
  void kill() {
    killed = true;
    if (!exit.isCompleted) exit.complete(1);
  }

  void emit(String line) => stdout.add(line);
}

SidecarController _controller(
  _FakeProcess process, {
  List<String> candidates = const [],
  bool attach = false,
  SidecarLauncher? launcher,
}) =>
    SidecarController(
      handshakeCandidates: candidates,
      attach: attach,
      launcher: launcher ?? (command, cwd, environment) async => process,
      environment: const {},
      parentPid: 1,
      startupTimeout: const Duration(seconds: 2),
      pollInterval: const Duration(milliseconds: 20),
    );

void main() {
  test('handshake из stdout', () async {
    final process = _FakeProcess();
    final controller = _controller(process, candidates: ['нет-такого.json']);
    final future = controller.start();
    await Future<void>.delayed(const Duration(milliseconds: 30));
    process.emit('обычный лог');
    process.emit('{"port": 5000, "token": "t"}');
    final ready = await future;
    expect(ready.port, 5000);
    expect(process.killed, isFalse);
  });

  test('handshake из api.json и удаление устаревшего', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-sidecar-poll');
    addTearDown(() => dir.deleteSync(recursive: true));
    final path = '${dir.path}/api.json';
    File(path).writeAsStringSync('{"port": 1, "token": "stale"}');
    final process = _FakeProcess();
    final controller = _controller(
      process,
      candidates: [path],
      launcher: (command, cwd, environment) async {
        Timer(const Duration(milliseconds: 60), () {
          File(path).writeAsStringSync('{"port": 6001, "token": "abc"}');
        });
        return process;
      },
    );
    final ready = await controller.start();
    expect(ready.port, 6001);
    expect(ready.token, 'abc');
  });

  test('смерть процесса до handshake → SidecarStartException', () async {
    final process = _FakeProcess();
    final controller = _controller(process, candidates: ['нет-такого.json']);
    final future = controller.start();
    await Future<void>.delayed(const Duration(milliseconds: 30));
    process.exit.complete(3);
    await expectLater(
      future,
      throwsA(
        isA<SidecarStartException>()
            .having((error) => error.exitCode, 'exitCode', 3),
      ),
    );
  });

  test('attach читает api.json и не трогает процесс', () async {
    final dir = Directory.systemTemp.createTempSync('ilt-sidecar-attach');
    addTearDown(() => dir.deleteSync(recursive: true));
    final path = '${dir.path}/api.json';
    File(path).writeAsStringSync('{"port": 7000, "token": "attach-token"}');
    final controller = _controller(
      _FakeProcess(),
      candidates: [path],
      attach: true,
      launcher: (command, cwd, environment) async =>
          throw StateError('launcher не должен вызываться'),
    );
    final ready = await controller.start();
    expect(ready.token, 'attach-token');
    controller.stop();
    expect(controller.ownsProcess, isFalse);
  });

  test('attach без api.json → SidecarStartException', () async {
    final controller = _controller(
      _FakeProcess(),
      candidates: ['нет-такого-файла.json'],
      attach: true,
    );
    await expectLater(
      controller.start(),
      throwsA(isA<SidecarStartException>()),
    );
  });

  test('stop убивает запущенный процесс', () async {
    final process = _FakeProcess();
    final controller = _controller(process, candidates: ['нет.json']);
    final future = controller.start();
    await Future<void>.delayed(const Duration(milliseconds: 30));
    process.emit('{"port": 5001, "token": "t"}');
    await future;
    expect(controller.ownsProcess, isTrue);
    controller.stop();
    expect(process.killed, isTrue);
    expect(controller.ownsProcess, isFalse);
  });

  test('команда запуска с --api и --parent-pid', () {
    final command = sidecarCommand(parentPid: 42, environment: const {});
    expect(command.length, greaterThanOrEqualTo(5));
    expect(command, contains('--api'));
    expect(command[command.indexOf('--parent-pid') + 1], '42');
    final custom = sidecarCommand(
      parentPid: 42,
      environment: const {'ILT_SIDECAR_EXE': 'C:\\app\\ilt_sidecar.exe'},
    );
    expect(custom.first, 'C:\\app\\ilt_sidecar.exe');
  });

  test('замороженная раскладка: сайдкар из sidecar/ и ILT_INSTALL_ROOT', () async {
    final root = Directory.systemTemp.createTempSync('ilt-frozen');
    addTearDown(() => root.deleteSync(recursive: true));
    final exe = File('${root.path}/sidecar/ImageLocalizationTool.exe');
    exe.createSync(recursive: true);
    final process = _FakeProcess();
    List<String>? seenCommand;
    Map<String, String>? seenEnv;
    final controller = SidecarController(
      handshakeCandidates: ['нет.json'],
      environment: const {},
      parentPid: 1,
      executableDir: '${root.path}/desktop',
      launcher: (command, cwd, environment) async {
        seenCommand = command;
        seenEnv = environment;
        return process;
      },
      startupTimeout: const Duration(seconds: 2),
      pollInterval: const Duration(milliseconds: 20),
    );
    final future = controller.start();
    await Future<void>.delayed(const Duration(milliseconds: 30));
    process.emit('{"port": 5002, "token": "t"}');
    await future;
    expect(seenCommand!.first, exe.path);
    expect(seenCommand, contains('--api'));
    expect(seenEnv, {'ILT_INSTALL_ROOT': root.path});
  });

  test('frozenSidecarPath вне раскладки → null', () {
    final root = Directory.systemTemp.createTempSync('ilt-frozen-none');
    addTearDown(() => root.deleteSync(recursive: true));
    expect(
      frozenSidecarPath(
        environment: const {},
        executableDir: '${root.path}/desktop',
      ),
      isNull,
    );
  });
}
