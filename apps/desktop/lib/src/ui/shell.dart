import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/shell_state.dart';
import 'file_dialogs.dart';
import 'inspector/inspector_rail.dart';
import 'pages_rail.dart';
import 'platform.dart';
import 'scene.dart';
import 'status_bar.dart';
import 'theme.dart';
import 'top_bar.dart';
import 'viewer/viewer_dock.dart';

/// Каркас оболочки: панель, рейки, сцена, док и строка состояния.
class ShellScreen extends StatelessWidget {
  const ShellScreen({
    super.key,
    required this.state,
    required this.onOpenSettings,
    required this.onOpenGlossary,
    required this.onOpenExport,
    required this.onOpenHotkeys,
    required this.onOpenRemote,
  });

  final ShellState state;
  final VoidCallback onOpenSettings;
  final VoidCallback onOpenGlossary;
  final Future<void> Function() onOpenExport;
  final VoidCallback onOpenHotkeys;
  final VoidCallback onOpenRemote;

  @override
  Widget build(BuildContext context) {
    final workspace = state.workspace;
    final metrics = ChromeMetrics.scaled(state.uiScale);
    final theme = buildIltTheme(
      themeName: state.themeName,
      scale: state.uiScale,
      platform: MediaQuery.platformBrightnessOf(context),
    );
    final actions = _actions();
    return Theme(
      data: theme,
      child: Scaffold(
        key: const Key('shell-scaffold'),
        backgroundColor: theme.colorScheme.surface,
        body: Column(
          children: [
            TopBar(
              workspace: workspace,
              hostStatus: state.status,
              sourceLang: state.sourceLang,
              targetLang: state.targetLang,
              metrics: metrics,
              actions: actions,
            ),
            if (workspace.errorText != null)
              _Strip(
                key: const Key('shell-error-strip'),
                color: theme.colorScheme.error,
                text: workspace.errorText!,
                onClose: workspace.clearError,
              ),
            if (state.secondary.errorText != null)
              _Strip(
                key: const Key('shell-secondary-strip'),
                color: theme.colorScheme.error,
                text: state.secondary.errorText!,
                onClose: state.secondary.clearError,
              ),
            if (state.secondary.lastExport != null)
              _Strip(
                key: const Key('shell-export-strip'),
                color: state.secondary.lastExport!.errors.isEmpty
                    ? const Color(0xFF7BD389)
                    : const Color(0xFFD9A441),
                text:
                    'Экспортировано страниц: '
                    '${state.secondary.lastExport!.saved}'
                    '${state.secondary.lastExport!.errors.isEmpty ? '' : ' · ошибок: ${state.secondary.lastExport!.errors.length}'}',
                onClose: state.secondary.clearLastExport,
              ),
            if (workspace.viewer.errorText != null)
              _Strip(
                key: const Key('shell-viewer-strip'),
                color: const Color(0xFFD9A441),
                text: workspace.viewer.errorText!,
                onClose: workspace.viewer.clearError,
              ),
            if (workspace.dirtyClose)
              _Strip(
                key: const Key('shell-dirty-strip'),
                color: theme.colorScheme.tertiary,
                text: 'Есть несохранённые изменения проекта.',
                action: TextButton(
                  key: const Key('dirty-close-force'),
                  onPressed: () => workspace.closeProject(force: true),
                  child: const Text('Закрыть без сохранения'),
                ),
                onClose: workspace.dismissDirtyClose,
              ),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PagesRail(workspace: workspace, metrics: metrics),
                  Expanded(
                    child: Stack(
                      children: [
                        Positioned.fill(
                          child: Scene(
                            workspace: workspace,
                            hostStatus: state.status,
                            metrics: metrics,
                            errorMessage: state.errorMessage,
                            onRetry: state.retry,
                            onOpenFiles: actions.openFiles,
                            onOpenFolder: actions.openFolder,
                          ),
                        ),
                        if (workspace.hasProject &&
                            workspace.activePage != null &&
                            state.status == HostStatus.ready)
                          Positioned.fill(
                            child: ViewerDockHost(workspace: workspace),
                          ),
                      ],
                    ),
                  ),
                  InspectorRail(
                    workspace: workspace,
                    metrics: metrics,
                    onOpenLog: () {
                      final path = state.logPath;
                      if (path != null) unawaited(openPath(path));
                    },
                  ),
                ],
              ),
            ),
            StatusBar(workspace: workspace, metrics: metrics),
          ],
        ),
      ),
    );
  }

  ShellActions _actions() => ShellActions(
        openFiles: () async {
          final paths = await pickFiles();
          if (paths.isNotEmpty) await state.workspace.importPaths(paths);
        },
        openFolder: () async {
          final folder = await pickFolder();
          if (folder != null) {
            await state.workspace.importPaths([folder], recursive: true);
          }
        },
        loadPackage: () async {
          final path = await pickPackageToOpen();
          if (path != null) await state.workspace.loadPackage(path);
        },
        savePackage: () async {
          final name = state.workspace.project?.name ?? 'project';
          final path = await pickPackageToSave('$name.ilt.zip');
          if (path != null) await state.workspace.savePackage(path);
        },
        closeProject: () => state.workspace.closeProject(),
        exit: () async {
          await ServicesBinding.instance
              .exitApplication(ui.AppExitType.cancelable);
        },
        openSettings: onOpenSettings,
        openGlossary: onOpenGlossary,
        openExport: onOpenExport,
        openHotkeys: onOpenHotkeys,
        openRemote: onOpenRemote,
      );
}

/// Полоса сообщения под верхней панелью (ошибки, несохранённый проект).
class _Strip extends StatelessWidget {
  const _Strip({
    super.key,
    required this.color,
    required this.text,
    this.action,
    this.onClose,
  });

  final Color color;
  final String text;
  final Widget? action;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: color.withValues(alpha: 0.16),
      padding: const EdgeInsets.only(left: 12, right: 4),
      child: Row(
        children: [
          Icon(Icons.info_outline, size: 14, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          ?action,
          IconButton(
            tooltip: 'Закрыть',
            iconSize: 14,
            onPressed: onClose,
            icon: const Icon(Icons.close),
          ),
        ],
      ),
    );
  }
}
