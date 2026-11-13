import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'src/app.dart';
import 'src/api/ilt_api.dart';
import 'src/quick/quick_app.dart';
import 'src/quick/window_bridge.dart';
import 'src/sidecar/handshake.dart';
import 'src/sidecar/sidecar_controller.dart';
import 'src/sidecar/single_instance.dart';
import 'src/sidecar/window_state.dart';
import 'src/state/shell_state.dart';
import 'src/ui/platform.dart' as platform;

/// Корневой engine владеет IPC и сайдкаром; второе окно — только клиент API.
Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  if (args.contains('--quick-view')) {
    await _quickView();
    return;
  }
  final attach = const String.fromEnvironment('ILT_ATTACH') == '1';
  final launch = LaunchRequest.fromArgs(args);
  final single = SingleInstance();
  if (!attach && await single.forwardIfRunning(args)) exit(0);
  final state = ShellState(sidecar: SidecarController(attach: attach));
  state.secondary.onOpenFolder = platform.openFolder;
  final host = _Host(state, single, quick: launch.mode == 'quick');
  host.bind();
  if (!attach) {
    try {
      await single.acquire(
        onLaunch: (request) => unawaited(host.launch(request)),
      );
    } on FileSystemException {
      await single.dispose();
      runApp(const StartupErrorApp());
      await hostWindows.invokeMethod<void>('showEditor');
      return;
    }
  }
  runApp(
    ValueListenableBuilder<bool>(
      valueListenable: host.editor,
      builder: (context, shown, child) =>
          shown ? IltApp(state: state) : const SizedBox.shrink(),
    ),
  );
  unawaited(host.start(launch));
}

/// Координатор сохраняет запросы второго запуска до готовности handshake.
class _Host {
  _Host(this.state, this.single, {required bool quick})
    : editor = ValueNotifier(!quick) {
    if (!quick) _restoreWindow();
  }
  final ShellState state;
  final SingleInstance single;
  final ValueNotifier<bool> editor;
  final window = WindowState();
  final started = Completer<void>();
  Future<void> _launches = Future.value();
  bool _geometryStarted = false;
  bool _closing = false;

  void _restoreWindow() {
    if (!_geometryStarted) {
      _geometryStarted = true;
      window.restore();
    }
    window.start();
  }

  void bind() {
    hostWindows.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'activateEditor':
          _restoreWindow();
          editor.value = true;
          if (call.arguments is Map) {
            final payload = (call.arguments as Map).cast<String, dynamic>();
            if (payload['quick_item_id'] is String) {
              await state.workspace.viewer.guardOrRun(() async {
                final collection = await state.api!.postJson(
                  '/api/quick/editor',
                  {'id': payload['quick_item_id']},
                );
                state.workspace.applyCollection(collection);
              });
            } else {
              state.workspace.applyCollection(payload);
            }
          }
        case 'closeRequested':
          await closeEditor();
        case 'quitRequested':
          // Скрытое окно не должно оборвать ещё работающий общий worker.
          final jobs = await state.api?.getJson('/api/jobs');
          if (jobs?['unfinished'] != true) await _exit();
      }
    });
    AppLifecycleListener(
      onExitRequested: () async {
        await closeEditor();
        return ui.AppExitResponse.cancel;
      },
    );
  }

  Future<void> start(LaunchRequest initial) async {
    await state.start();
    try {
      await _handleLaunch(initial);
    } catch (_) {
      await hostWindows.invokeMethod<void>('showEditor');
    } finally {
      started.complete();
    }
  }

  Future<void> launch(LaunchRequest request) {
    final next = _launches.then((_) async {
      await started.future;
      await _handleLaunch(request);
    });
    // Ошибка одного IPC-запроса не блокирует последующие.
    _launches = next.catchError((Object error) async {
      await hostWindows.invokeMethod<void>('showEditor');
    });
    return _launches;
  }

  Future<void> _handleLaunch(LaunchRequest request) async {
    final api = state.api;
    if (api == null) {
      await hostWindows.invokeMethod<void>('showEditor');
      return;
    }
    if (request.mode == 'quick') {
      if (request.paths.isNotEmpty) {
        await api.postJson('/api/quick/accept', {'paths': request.paths});
      }
      final ready = state.ready!;
      await hostWindows.invokeMethod<void>('showQuick', {
        'port': ready.port,
        'token': ready.token,
      });
    } else {
      if (request.paths.isNotEmpty) {
        state.workspace.applyCollection(
          await api.postJson('/api/drop', {'paths': request.paths}),
        );
      }
      await hostWindows.invokeMethod<void>('showEditor');
    }
  }

  Future<void> closeEditor() async {
    if (_closing) return;
    _closing = true;
    try {
      final quick = await state.api?.getJson('/api/quick/session');
      final visible =
          await hostWindows.invokeMethod<bool>('visibleQuick') ?? false;
      if (quick?['busy'] == true || visible) {
        window.saveNow();
        await hostWindows.invokeMethod<void>('hide');
      } else if (await state.confirmExit() == ui.AppExitResponse.exit) {
        await _exit();
      }
    } finally {
      _closing = false;
    }
  }

  Future<void> _exit() async {
    if (_geometryStarted) window.saveNow();
    await single.dispose();
    state.dispose();
    await hostWindows.invokeMethod<void>('exit');
  }
}

Future<void> _quickView() async {
  final data = await hostWindows.invokeMapMethod<String, dynamic>('getApi');
  final ready = data == null ? null : ApiReady.tryParse(jsonEncode(data));
  if (ready == null) {
    hostWindows.setMethodCallHandler((call) async {
      if (call.method == 'closeRequested') {
        await hostWindows.invokeMethod<void>('quit');
      }
    });
    runApp(
      const MaterialApp(
        home: Scaffold(body: Center(child: Text('Сайдкар недоступен'))),
      ),
    );
    return;
  }
  final controller = QuickController(IltApi(ready: ready));
  var closing = false;
  hostWindows.setMethodCallHandler((call) async {
    if (call.method != 'closeRequested' || closing) return;
    closing = true;
    try {
      final session = await controller.api.getJson('/api/quick/session');
      await hostWindows.invokeMethod<void>('hide');
      if (session['busy'] != true &&
          await hostWindows.invokeMethod<bool>('visibleEditor') != true) {
        await hostWindows.invokeMethod<void>('quit');
      }
    } finally {
      closing = false;
    }
  });
  runApp(
    QuickApp(
      controller: controller,
      onOpenEditor: (payload) async {
        await hostWindows.invokeMethod<void>('showEditor', payload);
      },
    ),
  );
  controller.start();
}
