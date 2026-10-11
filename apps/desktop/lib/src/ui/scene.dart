import 'package:flutter/material.dart';

import '../state/shell_state.dart';
import '../state/workspace_state.dart';
import 'theme.dart';
import 'viewer/viewer_pane.dart';

/// Центральная сцена: пустое окно или просмотрщик (023).
class Scene extends StatelessWidget {
  const Scene({
    super.key,
    required this.workspace,
    required this.hostStatus,
    required this.metrics,
    required this.onOpenFiles,
    required this.onOpenFolder,
    required this.onRetry,
    this.errorMessage,
  });

  final WorkspaceState workspace;
  final HostStatus hostStatus;
  final ChromeMetrics metrics;
  final Future<void> Function() onOpenFiles;
  final Future<void> Function() onOpenFolder;
  final VoidCallback? onRetry;
  final String? errorMessage;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Container(
      key: const Key('shell-scene'),
      color: palette.bgScene,
      child: switch (hostStatus) {
        HostStatus.starting => const _Starting(),
        HostStatus.error => _Error(message: errorMessage, onRetry: onRetry),
        HostStatus.ready => workspace.hasProject
            ? ViewerPane(workspace: workspace)
            : _EmptyScene(
                workspace: workspace,
                metrics: metrics,
                onOpenFiles: onOpenFiles,
                onOpenFolder: onOpenFolder,
              ),
      },
    );
  }
}

class _Starting extends StatelessWidget {
  const _Starting();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          CircularProgressIndicator(),
          SizedBox(height: 12),
          Text('Запуск локального API…'),
        ],
      ),
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({this.message, this.onRetry});

  final String? message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, color: theme.colorScheme.error),
            const SizedBox(height: 8),
            Text(
              message ?? 'Не удалось запустить сайдкар',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('shell-retry'),
              onPressed: onRetry,
              child: const Text('Повторить'),
            ),
          ],
        ),
      ),
    );
  }
}

/// Пустое окно: дропзона и недавние проекты.
class _EmptyScene extends StatelessWidget {
  const _EmptyScene({
    required this.workspace,
    required this.metrics,
    required this.onOpenFiles,
    required this.onOpenFolder,
  });

  final WorkspaceState workspace;
  final ChromeMetrics metrics;
  final Future<void> Function() onOpenFiles;
  final Future<void> Function() onOpenFolder;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                key: const Key('empty-dropzone'),
                padding: const EdgeInsets.all(28),
                decoration: BoxDecoration(
                  color: palette.surface1,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: palette.border),
                ),
                child: Column(
                  children: [
                    Icon(Icons.folder_open, size: 40, color: palette.primary),
                    const SizedBox(height: 12),
                    Text(
                      'Перетащите сюда главу',
                      style: theme.textTheme.titleSmall,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Папка, cbz/cbr/zip или страницы — язык определится сам.',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall,
                    ),
                    const SizedBox(height: 16),
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        FilledButton(
                          key: const Key('empty-open-files'),
                          onPressed: onOpenFiles,
                          child: const Text('Открыть файлы…'),
                        ),
                        OutlinedButton(
                          key: const Key('empty-open-folder'),
                          onPressed: onOpenFolder,
                          child: const Text('Открыть папку…'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Ctrl+O — файлы, Ctrl+Shift+O — папка',
                      style: theme.textTheme.labelSmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              _Recent(workspace: workspace),
            ],
          ),
        ),
      ),
    );
  }
}

class _Recent extends StatelessWidget {
  const _Recent({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final recent = workspace.recent;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Text('Недавние проекты', style: theme.textTheme.labelMedium),
            const Spacer(),
            if (recent.isNotEmpty)
              TextButton(
                key: const Key('recent-clear'),
                onPressed: workspace.clearRecent,
                child: const Text('Очистить'),
              ),
          ],
        ),
        if (recent.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              'Пока пусто — откройте главу, и она появится здесь.',
              key: const Key('recent-empty'),
              style: theme.textTheme.bodySmall,
            ),
          )
        else
          for (final entry in recent)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: InkWell(
                key: Key('recent-${entry.id}'),
                borderRadius: BorderRadius.circular(8),
                onTap: () => workspace.openRecent(entry.id),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: palette.surface1,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: palette.line),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        Icons.folder_outlined,
                        size: 16,
                        color: palette.textMuted,
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              entry.name.isEmpty ? entry.id : entry.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: palette.textPrimary),
                            ),
                            if (entry.path.isNotEmpty)
                              Text(
                                entry.path,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.labelSmall,
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
      ],
    );
  }
}
