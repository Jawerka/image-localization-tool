import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'src/app.dart';
import 'src/sidecar/sidecar_controller.dart';
import 'src/sidecar/single_instance.dart';
import 'src/sidecar/window_focus.dart';
import 'src/state/shell_state.dart';
import 'src/ui/platform.dart' as platform;

/// Точка входа хоста.
///
/// `--dart-define=ILT_ATTACH=1` — подключиться к уже запущенному сайдкару
/// (`python -m src.app --api`) без запуска и остановки процесса.
Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  final attach = const String.fromEnvironment('ILT_ATTACH') == '1';
  final single = SingleInstance();
  if (!attach && await single.forwardIfRunning(args)) {
    exit(0);
  }
  final state = ShellState(sidecar: SidecarController(attach: attach));
  state.secondary.onOpenFolder = platform.openFolder;
  if (!attach) {
    try {
      await single.acquire(onPaths: (paths) => _onSecondLaunch(state, paths));
    } on FileSystemException {
      await single.dispose();
      runApp(const StartupErrorApp());
      return;
    }
  }
  // Слушатель держит ссылку сам WidgetsBinding: он нужен, чтобы убрать
  // instance.json при штатном выходе. При незавершённом прогоне выход
  // подтверждается диалогом (ShellRoot).
  AppLifecycleListener(
    onExitRequested: () async {
      final response = await state.confirmExit();
      if (response == ui.AppExitResponse.exit) {
        await single.dispose();
      }
      return response;
    },
  );
  runApp(IltApp(state: state));
  unawaited(state.start());
}

/// Второй запуск: сфокусировать окно первого экземпляра, затем отправить
/// его пути в сайдкар (`POST /api/drop`) и показать результат.
Future<void> _onSecondLaunch(ShellState state, List<String> paths) async {
  focusMainWindow();
  final api = state.api;
  if (api == null || paths.isEmpty) return;
  try {
    final payload = await api.postJson('/api/drop', {'paths': paths});
    state.workspace.applyCollection(payload);
  } catch (_) {
    // Сайдкар занят/недоступен — второй запуск не должен падать.
  }
}
