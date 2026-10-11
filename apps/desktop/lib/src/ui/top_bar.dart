import 'package:flutter/material.dart';

import '../state/shell_state.dart';
import '../state/workspace_state.dart';
import 'theme.dart';

/// Действия меню «Файл» и панели, собираются в `shell.dart`.
class ShellActions {
  const ShellActions({
    required this.openFiles,
    required this.openFolder,
    required this.loadPackage,
    required this.savePackage,
    required this.closeProject,
    required this.exit,
    required this.openSettings,
    required this.openGlossary,
    required this.openExport,
    required this.openHotkeys,
    required this.openRemote,
  });

  final Future<void> Function() openFiles;
  final Future<void> Function() openFolder;
  final Future<void> Function() loadPackage;
  final Future<void> Function() savePackage;
  final Future<void> Function() closeProject;
  final Future<void> Function() exit;
  final VoidCallback openSettings;
  final VoidCallback openGlossary;
  final VoidCallback openExport;
  final VoidCallback openHotkeys;
  final VoidCallback openRemote;
}

/// Верхняя панель: меню «Файл», проект, языки, режимы и действия.
class TopBar extends StatelessWidget {
  const TopBar({
    super.key,
    required this.workspace,
    required this.hostStatus,
    required this.sourceLang,
    required this.targetLang,
    required this.metrics,
    required this.actions,
  });

  final WorkspaceState workspace;
  final HostStatus hostStatus;
  final String sourceLang;
  final String targetLang;
  final ChromeMetrics metrics;
  final ShellActions actions;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final workspace = this.workspace;
    final project = workspace.project;
    return Container(
      key: const Key('shell-top-bar'),
      height: metrics.appBarHeight,
      padding: EdgeInsets.symmetric(horizontal: 8 * metrics.appBarHeight / 46),
      decoration: BoxDecoration(
        color: palette.surface1,
        border: Border(bottom: BorderSide(color: palette.line)),
      ),
      child: Row(
        children: [
          _FileMenu(workspace: workspace, actions: actions, enabled: true),
          SizedBox(width: 8 * metrics.appBarHeight / 46),
          Icon(
            Icons.translate,
            size: metrics.appBarHeight * 0.42,
            color: palette.primary,
          ),
          const SizedBox(width: 8),
          Text('Image Localization Tool', style: theme.textTheme.labelMedium),
          const SizedBox(width: 12),
          if (project == null)
            _chip(context, 'Проект не открыт')
          else
            _ProjectChip(project: project, pages: workspace.pages.length),
          const Spacer(),
          if (workspace.hasProject)
            _LangChip(source: sourceLang, target: targetLang),
          if (workspace.hasProject) const SizedBox(width: 8),
          if (workspace.hasProject)
            _ModeSegment(
              workspace: workspace,
              enabled: !workspace.busy,
              height: metrics.appBarHeight * 0.62,
            ),
          if (workspace.busy) ...[
            const SizedBox(width: 8),
            _JobPill(workspace: workspace, height: metrics.appBarHeight * 0.68),
          ],
          const SizedBox(width: 8),
          _TranslateButton(workspace: workspace),
          const SizedBox(width: 8),
          Tooltip(
            message: workspace.pages.any((page) => page.isReady)
                ? 'Экспорт… (Ctrl+E)'
                : 'Нет готовых страниц для экспорта',
            child: OutlinedButton.icon(
              key: const Key('top-export'),
              onPressed: workspace.pages.any((page) => page.isReady)
                  ? actions.openExport
                  : null,
              icon: const Icon(Icons.ios_share, size: 14),
              label: const Text('Экспорт'),
            ),
          ),
          IconButton(
            key: const Key('top-remote'),
            tooltip: 'Доступ по сети',
            onPressed: actions.openRemote,
            icon: const Icon(Icons.public),
          ),
          IconButton(
            key: const Key('top-settings'),
            tooltip: 'Настройки (Ctrl+,)',
            onPressed: actions.openSettings,
            icon: const Icon(Icons.settings_outlined),
          ),
          _HostChip(status: hostStatus),
        ],
      ),
    );
  }

  Widget _chip(BuildContext context, String text) => Container(
        key: const Key('top-project-chip'),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: IltPalette.of(context).surface3,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(text, style: Theme.of(context).textTheme.labelSmall),
      );
}

class _FileMenu extends StatelessWidget {
  const _FileMenu({
    required this.workspace,
    required this.actions,
    required this.enabled,
  });

  final WorkspaceState workspace;
  final ShellActions actions;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final hasProject = workspace.hasProject;
    return PopupMenuButton<String>(
      key: const Key('top-file-menu'),
      tooltip: 'Файл',
      enabled: enabled,
      onSelected: (value) {
        switch (value) {
          case 'open-files':
            actions.openFiles();
          case 'open-folder':
            actions.openFolder();
          case 'load-package':
            actions.loadPackage();
          case 'save-package':
            actions.savePackage();
          case 'close-project':
            actions.closeProject();
          case 'settings':
            actions.openSettings();
          case 'glossary':
            actions.openGlossary();
          case 'hotkeys':
            actions.openHotkeys();
          case 'export':
            actions.openExport();
          case 'exit':
            actions.exit();
        }
      },
      itemBuilder: (context) {
        final canExport = workspace.pages.any((page) => page.isReady);
        return [
          const PopupMenuItem(
            value: 'open-files',
            child: Text('Открыть файлы… (Ctrl+O)'),
          ),
          const PopupMenuItem(
            value: 'open-folder',
            child: Text('Открыть папку… (Ctrl+Shift+O)'),
          ),
          const PopupMenuDivider(),
          const PopupMenuItem(
            value: 'load-package',
            child: Text('Загрузить проект…'),
          ),
          PopupMenuItem(
            value: 'save-package',
            enabled: hasProject,
            child: const Text('Сохранить проект…'),
          ),
          PopupMenuItem(
            value: 'close-project',
            enabled: hasProject,
            child: const Text('Закрыть проект'),
          ),
          PopupMenuItem(
            value: 'export',
            enabled: canExport,
            child: const Text('Экспорт… (Ctrl+E)'),
          ),
          const PopupMenuDivider(),
          PopupMenuItem(
            value: 'glossary',
            enabled: hasProject,
            child: const Text('Глоссарий…'),
          ),
          const PopupMenuItem(
            value: 'settings',
            child: Text('Настройки… (Ctrl+,)'),
          ),
          const PopupMenuItem(
            value: 'hotkeys',
            child: Text('Горячие клавиши… (F1)'),
          ),
          const PopupMenuDivider(),
          const PopupMenuItem(value: 'exit', child: Text('Выход')),
        ];
      },
      child: Container(
        height: 26,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: palette.border),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.article_outlined, size: 13, color: palette.textMuted),
            const SizedBox(width: 5),
            Text('Файл', style: Theme.of(context).textTheme.labelSmall),
          ],
        ),
      ),
    );
  }
}

class _ProjectChip extends StatelessWidget {
  const _ProjectChip({required this.project, required this.pages});

  final ProjectInfo project;
  final int pages;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: IltPalette.of(context).surface2,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.folder_outlined, size: 13, color: theme.colorScheme.primary),
          const SizedBox(width: 6),
          Text(project.name, style: theme.textTheme.labelMedium),
          const SizedBox(width: 6),
          Text(
            '$pages ${_pagesWord(pages)}',
            style: theme.textTheme.labelSmall,
          ),
        ],
      ),
    );
  }

  static String _pagesWord(int count) {
    final abs = count.abs() % 100;
    final last = abs % 10;
    if (abs > 10 && abs < 20) return 'страниц';
    if (last == 1) return 'страница';
    if (last >= 2 && last <= 4) return 'страницы';
    return 'страниц';
  }
}

class _LangChip extends StatelessWidget {
  const _LangChip({required this.source, required this.target});

  final String source;
  final String target;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Tooltip(
      message: 'Языки перевода',
      child: Container(
        key: const Key('top-langs'),
        height: 26,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: palette.border),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              source.toUpperCase(),
              style: Theme.of(context).textTheme.labelSmall,
            ),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 4),
              child: Icon(Icons.arrow_forward, size: 12),
            ),
            Text(
              target.toUpperCase(),
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _ModeSegment extends StatelessWidget {
  const _ModeSegment({
    required this.workspace,
    required this.enabled,
    required this.height,
  });

  final WorkspaceState workspace;
  final bool enabled;
  final double height;

  static const modes = [
    ('select', 'Отбор'),
    ('retouch', 'Ретушь'),
    ('run', 'Прогон'),
  ];

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Container(
      key: const Key('top-modes'),
      height: height,
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: palette.line),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final (value, label) in modes)
            _segment(context, value, label, palette),
        ],
      ),
    );
  }

  Widget _segment(
    BuildContext context,
    String value,
    String label,
    IltPalette palette,
  ) {
    final active = workspace.mode == value;
    return InkWell(
      onTap: enabled ? () => workspace.setMode(value) : null,
      borderRadius: BorderRadius.circular(5),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active ? palette.surface3 : Colors.transparent,
          borderRadius: BorderRadius.circular(5),
        ),
        child: Text(
          label,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: active
                    ? palette.textPrimary
                    : palette.textMuted.withValues(alpha: 0.8),
              ),
        ),
      ),
    );
  }
}

class _JobPill extends StatelessWidget {
  const _JobPill({required this.workspace, required this.height});

  final WorkspaceState workspace;
  final double height;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final paused = workspace.paused;
    return Container(
      key: const Key('top-job-pill'),
      height: height,
      padding: const EdgeInsets.only(left: 10, right: 2),
      decoration: BoxDecoration(
        color: palette.surface2,
        borderRadius: BorderRadius.circular(height / 2),
        border: Border.all(color: palette.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (!paused)
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: palette.primary,
              ),
            )
          else
            Icon(Icons.pause, size: 13, color: palette.textWarning),
          const SizedBox(width: 6),
          Text(
            paused
                ? 'Перевод · пауза'
                : 'Перевод · ${workspace.jobPercent} %',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: palette.textPrimary),
          ),
          IconButton(
            key: const Key('top-job-stop'),
            tooltip: 'Остановить',
            visualDensity: VisualDensity.compact,
            iconSize: 14,
            onPressed: workspace.cancelJobs,
            icon: const Icon(Icons.stop),
          ),
        ],
      ),
    );
  }
}

class _TranslateButton extends StatelessWidget {
  const _TranslateButton({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final active = workspace.activePage;
    final canPage = workspace.hasProject && active != null && !workspace.busy;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        FilledButton(
          key: const Key('top-translate'),
          onPressed: canPage ? () => workspace.translate(pageId: active.id) : null,
          child: const Text('Перевести'),
        ),
        PopupMenuButton<String>(
          key: const Key('top-translate-menu'),
          tooltip: 'Область перевода',
          enabled: workspace.hasProject && !workspace.busy,
          onSelected: (value) {
            if (value == 'all') workspace.translate();
          },
          itemBuilder: (context) => const [
            PopupMenuItem(value: 'all', child: Text('Перевести всё')),
            PopupMenuItem(
              value: 'settings',
              enabled: false,
              child: Text('Настройки перевода…'),
            ),
          ],
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 2),
            child: Icon(Icons.arrow_drop_down),
          ),
        ),
      ],
    );
  }
}

class _HostChip extends StatelessWidget {
  const _HostChip({required this.status});

  final HostStatus status;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (label, color) = switch (status) {
      HostStatus.starting => ('Запуск…', Colors.orange),
      HostStatus.ready => ('Готово', Colors.green),
      HostStatus.error => ('Ошибка', theme.colorScheme.error),
    };
    return Container(
      key: const Key('shell-status'),
      margin: const EdgeInsets.only(left: 6),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(label, style: theme.textTheme.labelSmall),
        ],
      ),
    );
  }
}
