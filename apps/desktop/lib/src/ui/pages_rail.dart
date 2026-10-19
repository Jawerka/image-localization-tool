import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/workspace_state.dart';
import 'labels.dart';
import 'page_thumb.dart';
import 'theme.dart';

/// Левая панель: список страниц, поиск, batch-блок и подвал.
class PagesRail extends StatefulWidget {
  const PagesRail({super.key, required this.workspace, required this.metrics});

  final WorkspaceState workspace;
  final ChromeMetrics metrics;

  @override
  State<PagesRail> createState() => _PagesRailState();
}

class _PagesRailState extends State<PagesRail> {
  String _tab = 'pages';

  WorkspaceState get workspace => widget.workspace;
  ChromeMetrics get metrics => widget.metrics;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Container(
      key: const Key('shell-pages-rail'),
      width: metrics.railWidth,
      decoration: BoxDecoration(
        color: palette.surface1,
        border: Border(right: BorderSide(color: palette.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(workspace: workspace, metrics: metrics),
          const Divider(height: 1),
          if (workspace.hasProject)
            _RailTabs(
              active: _tab,
              onChanged: (value) => setState(() => _tab = value),
            ),
          if (!workspace.hasProject)
            const Expanded(child: _Empty())
          else if (_tab == 'pages') ...[
            _Search(workspace: workspace),
            if (workspace.busy) _BatchBlock(workspace: workspace),
            Expanded(child: _PageList(workspace: workspace)),
            _Footer(workspace: workspace),
          ] else ...[
            _BatchBlock(workspace: workspace),
            Expanded(child: _QueueList(workspace: workspace)),
            _Footer(workspace: workspace),
          ],
        ],
      ),
    );
  }
}

class _RailTabs extends StatelessWidget {
  const _RailTabs({required this.active, required this.onChanged});

  final String active;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    Widget tab(String value, String label, Key key) {
      final selected = active == value;
      return Expanded(
        child: InkWell(
          key: key,
          onTap: () => onChanged(value),
          child: Container(
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(vertical: 6),
            decoration: BoxDecoration(
              color: selected ? palette.surface2 : Colors.transparent,
              border: Border(
                bottom: BorderSide(
                  color: selected ? palette.primary : Colors.transparent,
                  width: 1.5,
                ),
              ),
            ),
            child: Text(
              label,
              style: theme.textTheme.labelSmall?.copyWith(
                color: selected ? palette.textPrimary : palette.textMuted,
              ),
            ),
          ),
        ),
      );
    }

    return Container(
      margin: const EdgeInsets.fromLTRB(8, 6, 8, 2),
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: palette.line),
      ),
      child: Row(
        children: [
          tab('pages', 'Страницы', const Key('pages-tab-pages')),
          tab('queue', 'Очередь', const Key('pages-tab-queue')),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.workspace, required this.metrics});

  final WorkspaceState workspace;
  final ChromeMetrics metrics;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Padding(
      padding: EdgeInsets.symmetric(
        horizontal: 10 * metrics.railWidth / 268,
        vertical: 8 * metrics.railWidth / 268,
      ),
      child: Row(
        children: [
          Icon(Icons.image_outlined, size: 16, color: palette.textMuted),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              (workspace.project?.name ?? '').trim().isEmpty
                  ? 'Проект'
                  : workspace.project!.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ),
          if (workspace.hasProject)
            Text(
              '${workspace.pages.length}',
              style: Theme.of(context).textTheme.labelSmall,
            ),
        ],
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Text(
        'Нет открытого проекта',
        key: const Key('pages-empty'),
        style: Theme.of(context).textTheme.bodySmall,
      ),
    );
  }
}

class _Search extends StatelessWidget {
  const _Search({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
      child: SizedBox(
        height: kFieldHeight,
        child: TextField(
          key: const Key('pages-search'),
          style: Theme.of(context).textTheme.bodySmall,
          textAlignVertical: TextAlignVertical.center,
          decoration: InputDecoration(
            hintText: 'Поиск по имени',
            contentPadding: const EdgeInsets.symmetric(horizontal: 10),
            filled: true,
            fillColor: palette.input,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(6),
              borderSide: BorderSide(color: palette.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(6),
              borderSide: BorderSide(color: palette.border),
            ),
          ),
          onChanged: workspace.setQuery,
        ),
      ),
    );
  }
}

class _BatchBlock extends StatelessWidget {
  const _BatchBlock({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final batch = workspace.batch;
    return Container(
      key: const Key('pages-batch'),
      margin: const EdgeInsets.all(8),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: palette.surface2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.playlist_play, size: 14, color: palette.primary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  workspace.paused ? 'Очередь на паузе' : 'Очередь',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: palette.textPrimary,
                  ),
                ),
              ),
              Text('${batch.percent} %', style: theme.textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: batch.total == 0 ? 0 : batch.finished / batch.total,
            ),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 4,
            runSpacing: 4,
            children: [
              _counter(
                context,
                'готово',
                batch.done + batch.offline,
                palette.textSuccess,
              ),
              _counter(
                context,
                'в работе',
                batch.running,
                palette.primaryHover,
              ),
              _counter(context, 'в очереди', batch.queued, palette.textMuted),
              _counter(context, 'ошибки', batch.errors, palette.textError),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: Tooltip(
                  message: workspace.paused ? 'Продолжить' : 'Пауза',
                  child: OutlinedButton(
                    key: const Key('batch-pause'),
                    onPressed: workspace.busyAction
                        ? null
                        : (workspace.paused
                              ? workspace.resume
                              : workspace.pause),
                    child: Icon(
                      workspace.paused ? Icons.play_arrow : Icons.pause,
                      size: 16,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Tooltip(
                  message: 'Остановить',
                  child: OutlinedButton(
                    key: const Key('batch-stop'),
                    onPressed: workspace.cancelJobs,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: palette.textError,
                    ),
                    child: const Icon(Icons.stop, size: 16),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _counter(BuildContext context, String label, int value, Color color) {
    final palette = IltPalette.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: palette.line),
      ),
      child: Text(
        '$label $value',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: value > 0 ? color : palette.textMuted,
        ),
      ),
    );
  }
}

class _QueueList extends StatelessWidget {
  const _QueueList({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final rows = [
      for (final page in workspace.pages)
        if (page.isQueued || page.isRunning || page.isProblem) page,
    ];
    if (rows.isEmpty) {
      return Center(
        child: Text(
          'Очередь пуста',
          key: const Key('queue-empty'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }
    return ListView.builder(
      key: const Key('queue-list'),
      padding: const EdgeInsets.symmetric(vertical: 4),
      itemCount: rows.length,
      itemBuilder: (context, index) {
        final page = rows[index];
        return _PageTile(
          key: ValueKey('queue-${page.id}'),
          workspace: workspace,
          page: page,
          index: workspace.pages.indexOf(page),
        );
      },
    );
  }
}

class _PageList extends StatelessWidget {
  const _PageList({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final pages = workspace.visiblePages;
    if (pages.isEmpty) {
      return Center(
        child: Text(
          workspace.query.isEmpty && !workspace.problemsOnly
              ? 'В проекте нет страниц'
              : 'Ничего не найдено',
          key: const Key('pages-no-results'),
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }
    final reorderable =
        workspace.query.trim().isEmpty &&
        !workspace.problemsOnly &&
        pages.length == workspace.pages.length;
    final tiles = <Widget>[];
    String? lastChapter;
    for (var index = 0; index < pages.length; index += 1) {
      final page = pages[index];
      String? header;
      if (page.chapter.isNotEmpty && page.chapter != lastChapter) {
        header = page.chapter;
      }
      lastChapter = page.chapter;
      tiles.add(
        _PageTile(
          key: ValueKey('tile-${page.id}'),
          workspace: workspace,
          page: page,
          index: index,
          header: header,
        ),
      );
    }
    if (!reorderable) {
      return ListView(
        key: const Key('pages-list'),
        padding: const EdgeInsets.symmetric(vertical: 4),
        children: tiles,
      );
    }
    return ReorderableListView.builder(
      key: const Key('pages-list'),
      padding: const EdgeInsets.symmetric(vertical: 4),
      itemCount: tiles.length,
      onReorderItem: (oldIndex, newIndex) {
        final ids = [for (final page in workspace.pages) page.id];
        final moved = ids.removeAt(oldIndex);
        ids.insert(newIndex, moved);
        workspace.reorderPages(ids);
      },
      itemBuilder: (context, index) => tiles[index],
    );
  }
}

class _PageTile extends StatelessWidget {
  const _PageTile({
    super.key,
    required this.workspace,
    required this.page,
    required this.index,
    this.header,
  });

  final WorkspaceState workspace;
  final PageRow page;
  final int index;
  final String? header;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final active = workspace.activeId == page.id;
    final selected = workspace.selectedIds.contains(page.id);
    final status = pageStatusText(page);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (header != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
            child: Text(
              header!.isEmpty ? 'Без главы' : header!,
              style: theme.textTheme.labelSmall?.copyWith(
                color: palette.textMuted,
              ),
            ),
          ),
        InkWell(
          key: Key('page-row-${page.id}'),
          onTap: () =>
              workspace.selectPage(page.id, toggle: _ctrlPressed(context)),
          child: Container(
            height: 83,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: active
                  ? palette.surface3
                  : (selected ? palette.surface2 : Colors.transparent),
              border: Border(
                left: BorderSide(
                  width: 2,
                  color: active ? palette.primary : Colors.transparent,
                ),
              ),
            ),
            child: Row(
              children: [
                Stack(
                  children: [
                    PageThumb(
                      workspace: workspace,
                      pageId: page.id,
                      status: page.status,
                    ),
                    Positioned(
                      right: 3,
                      bottom: 3,
                      child: Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: statusColor(palette, page.status),
                          shape: BoxShape.circle,
                          boxShadow: const [
                            BoxShadow(
                              color: Color(0xA6080A0E),
                              blurRadius: 0,
                              spreadRadius: 2,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 22,
                  child: Text(
                    '${index + 1}'.padLeft(2, '0'),
                    style: theme.textTheme.labelSmall,
                  ),
                ),
                const SizedBox(width: 4),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        page.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: palette.textPrimary,
                        ),
                      ),
                      Text(
                        status,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: page.isProblem
                              ? palette.textError
                              : palette.textMuted,
                        ),
                      ),
                      if (page.isRunning)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(2),
                            child: LinearProgressIndicator(
                              value: page.progress / 100,
                              minHeight: 4,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                _RowMenu(workspace: workspace, page: page, index: index),
              ],
            ),
          ),
        ),
      ],
    );
  }

  static bool _ctrlPressed(BuildContext context) {
    final keyboard = HardwareKeyboard.instance;
    return keyboard.isControlPressed || keyboard.isMetaPressed;
  }
}

class _RowMenu extends StatelessWidget {
  const _RowMenu({
    required this.workspace,
    required this.page,
    required this.index,
  });

  final WorkspaceState workspace;
  final PageRow page;
  final int index;

  @override
  Widget build(BuildContext context) {
    final pages = workspace.pages;
    final canUp = !workspace.busy && index > 0;
    final canDown = !workspace.busy && index < pages.length - 1;
    return PopupMenuButton<String>(
      key: Key('page-menu-${page.id}'),
      tooltip: 'Ещё',
      iconSize: 14,
      onSelected: (value) {
        switch (value) {
          case 'up':
            _move(-1);
          case 'down':
            _move(1);
          case 'remove':
            _remove(context);
        }
      },
      itemBuilder: (context) => [
        PopupMenuItem(value: 'up', enabled: canUp, child: const Text('Выше')),
        PopupMenuItem(
          value: 'down',
          enabled: canDown,
          child: const Text('Ниже'),
        ),
        const PopupMenuDivider(),
        const PopupMenuItem(value: 'remove', child: Text('Удалить')),
      ],
      icon: Icon(Icons.more_vert, color: IltPalette.of(context).textMuted),
    );
  }

  void _move(int delta) {
    final ids = [for (final row in workspace.pages) row.id];
    final from = ids.indexOf(page.id);
    if (from < 0) return;
    final to = from + delta;
    if (to < 0 || to >= ids.length) return;
    ids.removeAt(from);
    ids.insert(to, page.id);
    workspace.reorderPages(ids);
  }

  Future<void> _remove(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text('Удалить «${page.name}» из проекта?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await workspace.removePages([page.id]);
    }
  }
}

class _Footer extends StatelessWidget {
  const _Footer({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final batch = workspace.batch;
    final problems = [
      for (final page in workspace.pages)
        if (page.isProblem) page,
    ];
    return Container(
      key: const Key('pages-footer'),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: palette.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${batch.finished} из ${batch.total} готово',
                  style: theme.textTheme.labelSmall,
                ),
              ),
              Text('${batch.percent} %', style: theme.textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: batch.total == 0 ? 0 : batch.finished / batch.total,
            ),
          ),
          const SizedBox(height: 8),
          if (problems.isNotEmpty)
            Tooltip(
              message: 'Оставить только проблемные страницы',
              child: OutlinedButton(
                key: const Key('pages-problems'),
                onPressed: () =>
                    workspace.setProblemsOnly(!workspace.problemsOnly),
                style: OutlinedButton.styleFrom(
                  foregroundColor: workspace.problemsOnly
                      ? palette.textError
                      : palette.textMuted,
                ),
                child: Text('${problems.length}'),
              ),
            ),
          if (problems.isNotEmpty && !workspace.busy) ...[
            const SizedBox(height: 6),
            OutlinedButton(
              key: const Key('pages-retry-errors'),
              onPressed: workspace.retryErrors,
              child: const Text('Повторить ошибки'),
            ),
          ],
        ],
      ),
    );
  }
}
