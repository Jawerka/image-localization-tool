import 'dart:io';

/// Найти корень репозитория для запуска `python -m src.app` из исходников.
///
/// Явный `ILT_REPO_ROOT` выигрывает; иначе поднимаемся от текущего каталога
/// (в dev это `apps/desktop`) до каталога с `src/app/desktop.py`.
String? findRepoRoot({Map<String, String>? environment, String? startDir}) {
  final env = environment ?? Platform.environment;
  final explicit = (env['ILT_REPO_ROOT'] ?? '').trim();
  if (explicit.isNotEmpty) return explicit;
  var dir = Directory(startDir ?? Directory.current.absolute.path);
  for (var i = 0; i < 8; i++) {
    if (File('${dir.path}/src/app/desktop.py').existsSync()) return dir.path;
    final parent = dir.parent;
    if (parent.path == dir.path) break;
    dir = parent;
  }
  return null;
}

/// Корень установки приложения.
///
/// В раскладке dist хост лежит в `{app}\desktop\`, поэтому корень — родитель
/// каталога exe. В dev это каталог сборочного дерева: кандидаты по нему
/// отсеются отсутствием `data`. `ILT_INSTALL_ROOT` перекрывает вычисление.
String? installRootDir({
  Map<String, String>? environment,
  String? executableDir,
}) {
  final env = environment ?? Platform.environment;
  final explicit = (env['ILT_INSTALL_ROOT'] ?? '').trim();
  if (explicit.isNotEmpty) return explicit;
  final exeDir = executableDir ?? File(Platform.resolvedExecutable).parent.path;
  if (exeDir.isEmpty) return null;
  final parent = Directory(exeDir).parent.path;
  if (parent == exeDir) return null;
  return parent;
}

/// Корни данных в порядке приоритета: env → портативный `data` → `%LOCALAPPDATA%`.
///
/// Порядок повторяет `src/app/paths.py`: портативный режим — каталог `data`
/// в корне установки; `desktop/data` (ассеты Flutter) пользовательским
/// каталогом не считается. Иначе на Windows `%LOCALAPPDATA%\ImageLocalizationTool`.
List<String> dataRootCandidates({
  Map<String, String>? environment,
  String? executableDir,
  String? repoRoot,
}) {
  final env = environment ?? Platform.environment;
  final roots = <String>[];
  final explicit = (env['ILT_DATA_DIR'] ?? '').trim();
  if (explicit.isNotEmpty) roots.add(explicit);
  if (repoRoot != null && repoRoot.isNotEmpty) {
    final portable = '$repoRoot/data';
    if (Directory(portable).existsSync()) roots.add(portable);
  }
  final installRoot = installRootDir(
    environment: environment,
    executableDir: executableDir,
  );
  if (installRoot != null && installRoot.isNotEmpty) {
    final portable = '$installRoot/data';
    if (Directory(portable).existsSync()) roots.add(portable);
  }
  final localAppData = (env['LOCALAPPDATA'] ?? '').trim();
  if (localAppData.isNotEmpty) {
    roots.add('$localAppData/ImageLocalizationTool');
  }
  return roots;
}

/// Каталог для записи `instance.json` (первый кандидат или текущий каталог).
String resolveDataRoot({
  Map<String, String>? environment,
  String? executableDir,
  String? repoRoot,
}) {
  final candidates = dataRootCandidates(
    environment: environment,
    executableDir: executableDir,
    repoRoot: repoRoot,
  );
  return candidates.isNotEmpty ? candidates.first : Directory.current.path;
}
