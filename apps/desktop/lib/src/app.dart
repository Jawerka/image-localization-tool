import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'state/shell_state.dart';
import 'ui/dialogs/exit_dialog.dart';
import 'ui/dialogs/export_dialog.dart';
import 'ui/dialogs/hotkeys_dialog.dart';
import 'ui/dialogs/worker_dialog.dart';
import 'ui/platform.dart';
import 'ui/screens/first_run_screen.dart';
import 'ui/screens/glossary_screen.dart';
import 'ui/screens/remote_screen.dart';
import 'ui/screens/settings_screen.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';
import 'ui/viewer/viewer_shortcuts.dart';

/// Причина отказа записи в каталог данных: portable нужно перенести.
const dataRootErrorText =
    'Папка приложения недоступна для записи. '
    'Распакуйте portable ZIP в папку, доступную для записи.';

/// Окно ошибки старта: показывается до запуска сайдкара.
class StartupErrorApp extends StatelessWidget {
  const StartupErrorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Image Localization Tool',
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Text(
              dataRootErrorText,
              key: const Key('startup-data-root-error'),
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }
}

/// Корневое приложение хоста: слушает [ShellState] и рисует каркас.
class IltApp extends StatelessWidget {
  const IltApp({super.key, required this.state});

  final ShellState state;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) {
        final workspace = state.workspace;
        final themeName = workspace.themeName;
        final scale = workspace.uiScale;
        // Тема на уровне MaterialApp: диалоги (`showDialog`) и оверлеи
        // ShellRoot живут вне `Theme` оболочки, без этого они светлые.
        return MaterialApp(
          title: 'Image Localization Tool',
          debugShowCheckedModeBanner: false,
          theme: buildIltTheme(themeName: 'light', scale: scale),
          darkTheme: buildIltTheme(themeName: 'dark', scale: scale),
          themeMode: switch (themeName) {
            'light' => ThemeMode.light,
            'dark' => ThemeMode.dark,
            _ => ThemeMode.system,
          },
          home: ShellRoot(state: state),
        );
      },
    );
  }
}

/// Оболочка плюс оверлеи и системные диалоги под общим набором хоткеев.
class ShellRoot extends StatefulWidget {
  const ShellRoot({super.key, required this.state});

  final ShellState state;

  @override
  State<ShellRoot> createState() => _ShellRootState();
}

class _ShellRootState extends State<ShellRoot> {
  bool _exitShown = false;
  bool _workerShown = false;
  bool _leaveShown = false;

  ShellState get state => widget.state;

  @override
  void initState() {
    super.initState();
    state.addListener(_onState);
    _onState();
  }

  @override
  void dispose() {
    state.removeListener(_onState);
    super.dispose();
  }

  void _onState() {
    if (!mounted) return;
    if (state.exitPrompt && !_exitShown) {
      _exitShown = true;
      unawaited(_showExit());
    }
    if (!state.exitPrompt) _exitShown = false;
    if (state.workerFailure != null && !_workerShown) {
      _workerShown = true;
      unawaited(_showWorker());
    }
    if (state.workerFailure == null) _workerShown = false;
    final viewer = state.workspace.viewer;
    if (viewer.leavePromptVisible && !_leaveShown) {
      _leaveShown = true;
      unawaited(_showLeave());
    }
    if (!viewer.leavePromptVisible) _leaveShown = false;
  }

  /// Диалог неприменённого черновика: применить / отменить / остаться.
  Future<void> _showLeave() async {
    final viewer = state.workspace.viewer;
    final choice = await showDialog<_LeaveChoice>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        key: const Key('viewer-leave-dialog'),
        title: const Text('Неприменённые правки'),
        content: const Text(
          'На странице есть правки, которые ещё не применены. '
          'Применить их, отменить или остаться на странице?',
        ),
        actions: [
          TextButton(
            key: const Key('viewer-leave-stay'),
            onPressed: () => Navigator.pop(context, _LeaveChoice.stay),
            child: const Text('Остаться'),
          ),
          TextButton(
            key: const Key('viewer-leave-discard'),
            onPressed: () => Navigator.pop(context, _LeaveChoice.discard),
            child: const Text('Отменить правки'),
          ),
          FilledButton(
            key: const Key('viewer-leave-apply'),
            onPressed: () => Navigator.pop(context, _LeaveChoice.apply),
            child: const Text('Применить'),
          ),
        ],
      ),
    );
    switch (choice) {
      case _LeaveChoice.apply:
        await viewer.commitLeave();
      case _LeaveChoice.discard:
        await viewer.discardLeave();
      default:
        viewer.cancelLeave();
    }
  }

  Future<void> _showExit() async {
    final unfinished = state.workspace.pages
        .where((page) => page.isQueued || page.isRunning)
        .length;
    final choice = await showDialog<ExitChoice>(
      context: context,
      barrierDismissible: false,
      builder: (context) => ExitDialog(
        pages: unfinished,
        total: state.workspace.pages.length,
      ),
    );
    switch (choice) {
      case ExitChoice.now:
        state.exitNow();
      case ExitChoice.wait:
        state.waitForBatchAndExit();
      default:
        state.cancelExit();
    }
  }

  Future<void> _showWorker() async {
    final message = state.workerFailure;
    if (message == null) return;
    final choice = await showDialog<WorkerChoice>(
      context: context,
      builder: (context) => WorkerDialog(message: message),
    );
    switch (choice) {
      case WorkerChoice.retry:
        state.dismissWorkerFailure();
        unawaited(state.workspace.retryErrors());
      case WorkerChoice.openLog:
        final path = state.logPath;
        if (path != null) unawaited(openPath(path));
        state.dismissWorkerFailure();
      default:
        state.dismissWorkerFailure();
    }
  }

  Future<void> _openExport() => showDialog<bool>(
        context: context,
        builder: (context) => ExportDialog(state: state),
      );

  Future<void> _openHotkeys() => showDialog<void>(
        context: context,
        builder: (context) => const HotkeysDialog(),
      );

  void _openSettings() => state.openOverlay(OverlayKind.settings);

  void _openGlossary() => state.openOverlay(OverlayKind.glossary);

  void _openRemote() => state.openOverlay(OverlayKind.remote);

  void _maybeOpenExport() {
    if (state.overlayOpen || state.showFirstRun) return;
    final ready =
        state.workspace.pages.where((page) => page.isReady).length;
    if (ready == 0) return;
    unawaited(_openExport());
  }

  void _onEscape() {
    if (state.overlayOpen) state.closeOverlay();
  }

  @override
  Widget build(BuildContext context) {
    final overlay = state.overlay;
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.escape): _onEscape,
        const SingleActivator(LogicalKeyboardKey.f1): _openHotkeys,
        const SingleActivator(LogicalKeyboardKey.comma, control: true):
            _openSettings,
        const SingleActivator(LogicalKeyboardKey.keyE, control: true):
            _maybeOpenExport,
      },
      child: Focus(
        autofocus: true,
        onKeyEvent: (node, event) => handleViewerShortcut(
          event,
          workspace: state.workspace,
          enabled: state.status == HostStatus.ready &&
              !state.overlayOpen &&
              !state.showFirstRun,
        ),
        child: Stack(
          children: [
            ShellScreen(
              state: state,
              onOpenSettings: _openSettings,
              onOpenGlossary: _openGlossary,
              onOpenExport: _openExport,
              onOpenHotkeys: _openHotkeys,
              onOpenRemote: _openRemote,
            ),
            if (state.showFirstRun)
              Material(
                color: Colors.transparent,
                child: FirstRunScreen(state: state),
              )
            else if (overlay == OverlayKind.settings)
              Material(
                color: Colors.transparent,
                child: SettingsScreen(state: state),
              )
            else if (overlay == OverlayKind.glossary)
              Material(
                color: Colors.transparent,
                child: GlossaryScreen(state: state),
              )
            else if (overlay == OverlayKind.remote)
              Material(
                color: Colors.transparent,
                child: RemoteScreen(state: state),
              ),
          ],
        ),
      ),
    );
  }
}

/// Выбор в диалоге неприменённых правок.
enum _LeaveChoice { apply, discard, stay }
