import 'dart:async';
import 'dart:io';

import 'data_root.dart';
import 'handshake.dart';
import 'sidecar_process.dart';

/// Ошибка запуска сайдкара: handshake не получен или процесс умер.
class SidecarStartException implements Exception {
  SidecarStartException(this.message, {this.exitCode});

  final String message;
  final int? exitCode;

  @override
  String toString() => message;
}

typedef SidecarLauncher = Future<SidecarProcess> Function(
  List<String> command,
  String? workingDirectory,
  Map<String, String>? environment,
);

/// Путь к замороженному сайдкару раскладки dist:
/// `{installRoot}\sidecar\ImageLocalizationTool.exe`.
String? frozenSidecarPath({
  Map<String, String>? environment,
  String? executableDir,
}) {
  final root = installRootDir(
    environment: environment,
    executableDir: executableDir,
  );
  if (root == null) return null;
  final path = '$root/sidecar/ImageLocalizationTool.exe';
  return File(path).existsSync() ? path : null;
}

/// Команда запуска сайдкара: env → замороженная раскладка → `python -m src.app`.
List<String> sidecarCommand({
  required int parentPid,
  Map<String, String>? environment,
  String? executableDir,
}) {
  final env = environment ?? Platform.environment;
  final exe = (env['ILT_SIDECAR_EXE'] ?? '').trim();
  if (exe.isNotEmpty) return [exe, '--api', '--parent-pid', '$parentPid'];
  final frozen = frozenSidecarPath(
    environment: environment,
    executableDir: executableDir,
  );
  if (frozen != null) return [frozen, '--api', '--parent-pid', '$parentPid'];
  final python = (env['ILT_PYTHON'] ?? 'python').trim();
  return [python, '-m', 'src.app', '--api', '--parent-pid', '$parentPid'];
}

Future<SidecarProcess> _defaultLauncher(
  List<String> command,
  String? workingDirectory,
  Map<String, String>? environment,
) async {
  final process = await Process.start(
    command.first,
    command.skip(1).toList(),
    workingDirectory: workingDirectory,
    environment: environment,
    runInShell: false,
  );
  return SidecarProcessIo(process);
}

/// Жизненный цикл сайдкара: запуск, ожидание handshake, остановка.
///
/// В attach-режиме ничего не запускает и не убивает: только читает
/// уже существующий `api.json` (dev-режим `python -m src.app --api`).
class SidecarController {
  SidecarController({
    List<String>? handshakeCandidates,
    this.attach = false,
    this.startupTimeout = const Duration(seconds: 20),
    this.pollInterval = const Duration(milliseconds: 100),
    SidecarLauncher? launcher,
    Map<String, String>? environment,
    int? parentPid,
    String? executableDir,
  })  : _environment = environment ?? Platform.environment,
        _parentPid = parentPid ?? pid,
        _executableDir = executableDir,
        _launcher = launcher ?? _defaultLauncher,
        handshakeCandidates = handshakeCandidates ??
            apiReadyCandidates(
              environment: environment,
              executableDir: executableDir,
              repoRoot: findRepoRoot(environment: environment),
            );

  final List<String> handshakeCandidates;
  final bool attach;
  final Duration startupTimeout;
  final Duration pollInterval;
  final Map<String, String> _environment;
  final int _parentPid;
  final String? _executableDir;
  final SidecarLauncher _launcher;
  SidecarProcess? _process;

  /// Поднять сайдкар (или подключиться к чужому в attach-режиме).
  Future<ApiReady> start() async {
    if (attach) {
      final ready = await readApiReadyFromFiles(handshakeCandidates);
      if (ready != null) return ready;
      throw SidecarStartException(
        'attach: api.json не найден (${handshakeCandidates.join(', ')})',
      );
    }
    removeStaleApiReady(handshakeCandidates);
    final frozen = frozenSidecarPath(
      environment: _environment,
      executableDir: _executableDir,
    );
    final command = sidecarCommand(
      parentPid: _parentPid,
      environment: _environment,
      executableDir: _executableDir,
    );
    // В раскладке dist рабочая папка и корень установки задаются явно:
    // сайдкар лежит в `sidecar\`, а модели, шрифты и `web` — в корне.
    final installRoot = frozen == null
        ? null
        : installRootDir(environment: _environment, executableDir: _executableDir);
    final cwd = findRepoRoot(environment: _environment) ?? installRoot;
    final env = installRoot == null
        ? null
        : <String, String>{'ILT_INSTALL_ROOT': installRoot};
    final process = await _launcher(command, cwd, env);
    _process = process;
    try {
      return await _waitHandshake(process);
    } catch (_) {
      process.kill();
      rethrow;
    }
  }

  /// Остановить запущенный нами сайдкар. Чужой процесс (attach) не трогаем.
  void stop() {
    final process = _process;
    _process = null;
    if (process == null || attach) return;
    process.kill();
  }

  /// true, если контроллер владеет процессом и должен его убивать.
  bool get ownsProcess => !attach && _process != null;

  /// Future завершения запущенного процесса; null без процесса (attach).
  Future<int>? get processExitCode => _process?.exitCode;

  Future<ApiReady> _waitHandshake(SidecarProcess process) async {
    ApiReady? fromStdout;
    final stderrTail = <String>[];
    final stdoutSub = process.stdoutLines.listen((line) {
      fromStdout ??= ApiReady.tryParse(line);
    });
    final stderrSub = process.stderrLines.listen((line) {
      stderrTail.add(line);
      if (stderrTail.length > 20) stderrTail.removeAt(0);
    });
    var exited = false;
    int? exitCode;
    unawaited(
      process.exitCode.then((code) {
        exited = true;
        exitCode = code;
      }),
    );
    final deadline = DateTime.now().add(startupTimeout);
    try {
      while (DateTime.now().isBefore(deadline)) {
        final ready =
            fromStdout ?? await readApiReadyFromFiles(handshakeCandidates);
        if (ready != null) return ready;
        if (exited) {
          final tail = stderrTail.isEmpty ? '' : ': ${stderrTail.last}';
          throw SidecarStartException(
            'Сайдкар завершился с кодом $exitCode$tail',
            exitCode: exitCode,
          );
        }
        await Future<void>.delayed(pollInterval);
      }
      throw SidecarStartException(
        'Сайдкар не ответил за ${startupTimeout.inSeconds} с',
      );
    } finally {
      await stdoutSub.cancel();
      await stderrSub.cancel();
    }
  }
}
