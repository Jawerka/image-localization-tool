// Сквозной smoke инспектора против живого сайдкара (шаг конвергенции 024).
//
// Запуск (из apps/desktop, с изолированным каталогом данных):
//   $env:ILT_DATA_DIR = "$env:TEMP\ilt-inspector-smoke"
//   $env:ILT_PYTHON = "<repo>\venv\Scripts\python.exe"
//   flutter run -d windows -t tool/inspector_smoke.dart
//
// Проверяет серверный контур инспектора без кликов: автосохранение текста,
// черновик стиля → «Готово», предпросмотр региона, стили проекта, сброс
// правок. UI-жесты покрыты widget-тестами.

import 'dart:async';
import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:ilt_desktop/src/model/page_document.dart';
import 'package:ilt_desktop/src/state/shell_state.dart';
import 'package:ilt_desktop/src/state/viewer_state.dart';
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
    if (state.status != HostStatus.ready) return;

    final workspace = state.workspace;
    final viewer = workspace.viewer;

    await workspace.importPaths([image.path]);
    _expect(workspace.pages.isNotEmpty,
        'импорт дал страницы: ${workspace.pages.length}');
    if (workspace.pages.isEmpty) return;
    final page = workspace.pages.first;
    if (!page.isReady) {
      await workspace.translate(pageId: page.id);
      final ready = await _waitUntil(
        'страница ${page.id} обработана',
        () =>
            workspace.pages.firstWhere((row) => row.id == page.id).isReady,
        timeout: const Duration(minutes: 10),
      );
      if (!ready) return;
    }

    await workspace.selectPage(page.id);
    await _waitUntil('документ загружен', () => viewer.document != null);
    final document = viewer.document;
    _expect(document != null, 'документ доступен');
    if (document == null) return;
    _expect(document.regions.isNotEmpty,
        'регионы найдены: ${document.regions.length}');
    final region = document.regions.first;

    // 1. Автосохранение текста (немедленный PUT) и translation_locked.
    final versionBeforeText = document.version;
    viewer.setRegionText(region.id, 'SMOKE TEXT');
    viewer.setRegionTranslation(region.id, 'СМОКЕ ТЕКСТ');
    await viewer.whenSaved(page.id);
    expectClean(viewer, 'текст сохранён без ошибок');
    final versionAfterText = viewer.document?.version ?? 0;
    _expect(versionAfterText > versionBeforeText,
        'версия выросла после текста: $versionBeforeText → $versionAfterText');
    _expect(
        viewer.document?.findRegion(region.id)?.data['translation_locked'] ==
            true,
        'translation_locked выставлен');

    // 2. Черновик стиля → «Готово».
    viewer.setRegionWarpPreset(region.id, 'wave');
    viewer.setRegionFontSize(region.id, 18);
    _expect(viewer.hasDeferredDraft, 'стиль лёг в черновик');
    final draftCount = viewer.editCount;
    _expect(draftCount >= 1, 'в пилюле правок: $draftCount');
    viewer.commitDeferredEdits();
    await viewer.whenSaved(page.id);
    expectClean(viewer, 'стиль сохранён без ошибок');
    final style = viewer.document?.findRegion(region.id)?.styleMap() ?? {};
    _expect(style['font_size_override'] == 18,
        'кегль записан: ${style['font_size_override']}');
    _expect((style['warp'] as Map?)?['kind'] == 'wave',
        'искривление записано: ${(style['warp'] as Map?)?['kind']}');

    // 3. Предпросмотр региона (PNG + X-Offset из сохранённого документа).
    viewer.selectRegion(null);
    viewer.selectRegion(region.id);
    final previewOk = await _waitUntil(
      'предпросмотр региона',
      () =>
          viewer.stylePreviewStatus == 'ready' ||
          viewer.stylePreviewStatus == 'error',
      timeout: const Duration(seconds: 60),
    );
    _expect(previewOk && viewer.stylePreviewStatus == 'ready',
        'предпросмотр готов: ${viewer.stylePreviewStatus} '
        '${viewer.stylePreviewMessage}');
    _expect(viewer.stylePreviewImage != null, 'PNG предпросмотра декодирован');

    // 4. Стили проекта: сохранение текущего стиля и перечитка.
    final projectId = workspace.project?.id ?? '';
    if (projectId.isNotEmpty) {
      await viewer.ensureStyles(projectId);
      final before = viewer.styleLibrary.length;
      final saved = await viewer.saveProjectStyle();
      _expect(saved, 'стиль проекта сохранён');
      _expect(viewer.styleLibrary.length >= before,
          'библиотека стилей: $before → ${viewer.styleLibrary.length}');
    } else {
      _expect(false, 'проект открыт (id для стилей)');
    }

    // 5. Шрифты каталога (наличие не гарантировано — только без ошибок).
    await viewer.ensureFonts();
    stdout.writeln('SMOKE_INFO fonts=${viewer.fonts.length}');

    // 6. Sfx-перекраска — если на странице есть звук.
    final sfxRegions =
        viewer.document?.regions.where((item) => item.isSfx).toList() ??
            const <Region>[];
    if (sfxRegions.isNotEmpty) {
      final sfxId = sfxRegions.first.id;
      await viewer.restyleSfx(sfxId);
      _expect(viewer.sfxStatus == 'ready',
          'стиль звука подобран: ${viewer.sfxStatus} ${viewer.sfxMessage}');
    } else {
      stdout.writeln('SMOKE_INFO sfx-регионов нет — подбор пропущен');
    }

    // 7. Сброс правок страницы.
    final beforeReset = viewer.document?.version ?? 0;
    await viewer.resetPage();
    await _waitUntil('документ перечитан после сброса', () {
      return viewer.document != null && !viewer.loading;
    });
    expectClean(viewer, 'сброс без ошибок');
    final afterReset = viewer.document?.version ?? 0;
    _expect(afterReset >= beforeReset,
        'версия после сброса: $beforeReset → $afterReset');
    _expect(viewer.canUndo == false, 'история очищена после сброса');

    stdout.writeln('SMOKE_RESULT regions=${viewer.document?.regions.length ?? 0} '
        'version=$afterReset failures=$_failures');
  } catch (error, stack) {
    _failures += 1;
    stdout.writeln('SMOKE_FAIL исключение: $error');
    stderr.writeln(stack);
  } finally {
    state.dispose();
  }
  stdout.writeln(
      _failures == 0 ? 'SMOKE_DONE' : 'SMOKE_DONE failures=$_failures');
  exit(_failures == 0 ? 0 : 1);
}

void expectClean(ViewerState viewer, String what) {
  final error = viewer.errorText;
  _expect(error == null, '$what: ${error ?? '-'}');
}
