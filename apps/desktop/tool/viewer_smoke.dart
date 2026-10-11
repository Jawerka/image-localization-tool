// Сквозной smoke просмотрщика против живого сайдкара (шаг конвергенции 023).
//
// Запуск (из apps/desktop, с изолированным каталогом данных):
//   $env:ILT_DATA_DIR = "$env:TEMP\ilt-smoke"
//   $env:ILT_PYTHON = "<repo>\venv\Scripts\python.exe"
//   flutter run -d windows -t tool/viewer_smoke.dart
//
// Проверяет: импорт страницы → документ и изображения из API → штрих кисти →
// «Готово» (PUT) → перевёрстка по событиям → перезагрузка документа и
// изображения новой версии. Никаких кликов: UI-жесты покрыты widget-тестами.

import 'dart:async';
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';
import 'package:ilt_desktop/src/sidecar/sidecar_controller.dart';

var _failures = 0;

void _expect(bool ok, String what) {
  if (ok) {
    stdout.writeln('SMOKE_OK  $what');
  } else {
    _failures += 1;
    stdout.writeln('SMOKE_FAIL $what');
  }
}

Future<bool> _waitUntil(
  String what,
  bool Function() test, {
  Duration timeout = const Duration(minutes: 5),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!test()) {
    if (DateTime.now().isAfter(deadline)) {
      _expect(false, '$what (таймаут)');
      return false;
    }
    await Future<void>.delayed(const Duration(milliseconds: 250));
  }
  return true;
}

File _resolveImage() {
  final raw = (Platform.environment['ILT_SMOKE_IMAGE'] ?? 'test-img\\test-1.jpg')
      .trim();
  final direct = File(raw);
  if (direct.isAbsolute && direct.existsSync()) return direct;
  var dir = Directory.current;
  for (var depth = 0; depth < 10; depth++) {
    final candidate = File('${dir.path}${Platform.pathSeparator}$raw');
    if (candidate.existsSync()) return candidate;
    final parent = dir.parent;
    if (parent.path == dir.path) break;
    dir = parent;
  }
  throw StateError('не найден $raw (cwd=${Directory.current.path})');
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = ShellState(sidecar: SidecarController());
  try {
    final image = _resolveImage();
    stdout.writeln('SMOKE_START image=${image.path} '
        'data=${Platform.environment['ILT_DATA_DIR'] ?? '-'}');
    await state.start();
    _expect(state.status == HostStatus.ready,
        'сайдкар готов (${state.errorMessage ?? state.status.name})');
    if (state.status != HostStatus.ready) {
      return;
    }
    final workspace = state.workspace;
    final viewer = workspace.viewer;

    await workspace.importPaths([image.path]);
    _expect(workspace.pages.isNotEmpty, 'импорт дал страницы: '
        '${workspace.pages.length}');
    if (workspace.pages.isEmpty) {
      return;
    }
    final page = workspace.pages.first;
    if (!page.isReady) {
      await workspace.translate(pageId: page.id);
      final ready = await _waitUntil(
        'страница ${page.id} обработана',
        () => workspace.pages
            .firstWhere((row) => row.id == page.id)
            .isReady,
        timeout: const Duration(minutes: 10),
      );
      if (!ready) {
        return;
      }
    }

    await workspace.selectPage(page.id);
    await _waitUntil('документ загружен', () => viewer.document != null);
    final document = viewer.document;
    _expect(document != null, 'документ доступен');
    if (document == null) {
      return;
    }
    _expect(document.regions.isNotEmpty,
        'регионы найдены: ${document.regions.length}');

    await _waitUntil(
      'изображение результата декодировано',
      () => viewer.imageFor('result') != null,
    );
    viewer.noteDisplayedImage(viewer.imageFor('result'));
    viewer.session.setImageSize(viewer.imageSize);
    _expect(viewer.imageSize.width > 0,
        'размер листа: ${viewer.imageSize.width.round()}'
        '×${viewer.imageSize.height.round()}');
    _expect(viewer.imageFor('mask') != null, 'маска декодирована');

    final versionBefore = document.version;
    final region = document.regions.first;
    final bbox = region.bbox;
    final point = bbox.center;
    viewer.editDocument(
      (doc) => doc.addStroke(
        Stroke(mode: Stroke.paint, radius: 6, points: [point]),
      ),
      deferApply: true,
    );
    _expect(viewer.hasDeferredDraft, 'штрих лёг в черновик');
    _expect(viewer.editCount == 1, 'в пилюле одна правка');
    viewer.commitDeferredEdits();
    await viewer.whenSaved(page.id);
    _expect(!viewer.isDirty(page.id), 'правка сохранена (PUT прошёл)');
    _expect(viewer.errorText == null, 'без ошибок: ${viewer.errorText ?? '-'}');
    _expect(!viewer.hasDeferredDraft, 'черновик применён');

    await _waitUntil(
      'страница ушла в перевёрстку',
      () {
        final row =
            workspace.pages.firstWhere((item) => item.id == page.id);
        return row.isRunning || row.isReady;
      },
    );
    await _waitUntil(
      'серверный статус после пересчёта',
      () {
        final row =
            workspace.pages.firstWhere((item) => item.id == page.id);
        return row.isReady;
      },
      timeout: const Duration(minutes: 10),
    );
    final versionAfter = viewer.document?.version ?? versionBefore;
    _expect(versionAfter != versionBefore,
        'версия документа обновилась: $versionBefore → $versionAfter');
    final freshResult = await _waitUntil(
      'свежее изображение новой версии декодировано',
      () => viewer.hasFreshImage('result'),
    );
    _expect(freshResult, 'результат перерисован для новой версии');

    stdout.writeln('SMOKE_RESULT pages=${workspace.pages.length} '
        'regions=${viewer.document?.regions.length ?? 0} '
        'version=$versionAfter failures=$_failures');
  } catch (error, stack) {
    _failures += 1;
    stdout.writeln('SMOKE_FAIL исключение: $error');
    stderr.writeln(stack);
  } finally {
    state.dispose();
  }
  stdout.writeln(_failures == 0 ? 'SMOKE_DONE' : 'SMOKE_DONE failures=$_failures');
  exit(_failures == 0 ? 0 : 1);
}
