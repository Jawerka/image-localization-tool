import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Минимальная абстракция процесса сайдкара (нужна, чтобы подменять в тестах).
abstract class SidecarProcess {
  Stream<String> get stdoutLines;
  Stream<String> get stderrLines;
  Future<int> get exitCode;
  void kill();
}

/// Процесс, запущенный через `Process.start`.
class SidecarProcessIo implements SidecarProcess {
  SidecarProcessIo(Process process) : _process = process {
    // Python на Windows пишет логи в консольной кодировке (cp1251/cp866):
    // строгий utf8 на такой строке бросает FormatException и «роняет» поток.
    const decoder = Utf8Decoder(allowMalformed: true);
    stdoutLines =
        _process.stdout.transform(decoder).transform(const LineSplitter());
    stderrLines =
        _process.stderr.transform(decoder).transform(const LineSplitter());
  }

  final Process _process;

  @override
  late final Stream<String> stdoutLines;

  @override
  late final Stream<String> stderrLines;

  @override
  Future<int> get exitCode => _process.exitCode;

  @override
  void kill() => _process.kill();
}
