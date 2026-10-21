import 'package:flutter/material.dart';

import '../../state/workspace_state.dart';
import '../labels.dart';
import '../theme.dart';
import 'canvas_view.dart';
import 'done_pill.dart';

/// Сцена редактора: канвас, чипы страницы, стрелки, пилюля правок.
class ViewerPane extends StatelessWidget {
  const ViewerPane({super.key, required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final viewer = workspace.viewer;
    final palette = IltPalette.of(context);
    final page = workspace.activePage;
    return AnimatedBuilder(
      animation: Listenable.merge([workspace, viewer]),
      builder: (context, _) {
        return Stack(
          children: [
            Positioned.fill(
              child: page == null
                  ? Center(
                      child: Text(
                        'Выберите страницу в списке слева',
                        key: const Key('scene-no-selection'),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    )
                  : CanvasView(viewer: viewer),
            ),
            if (page != null) ...[
              Positioned(
                left: 10,
                top: 10,
                child: _Marks(
                  pageName: page.name,
                  pageNumber: _pageNumber(workspace, page.id),
                  regions: viewer.document?.regions.length ?? 0,
                  overflow: viewer.document?.overflowCount ?? 0,
                  palette: palette,
                ),
              ),
              _NavArrow(
                alignment: Alignment.centerLeft,
                keyName: 'viewer-page-prev',
                icon: Icons.chevron_left,
                onTap: _hasNeighbor(-1)
                    ? () => workspace.stepPage(-1)
                    : null,
              ),
              _NavArrow(
                alignment: Alignment.centerRight,
                keyName: 'viewer-page-next',
                icon: Icons.chevron_right,
                onTap: _hasNeighbor(1)
                    ? () => workspace.stepPage(1)
                    : null,
              ),
              if (viewer.hasDeferredDraft || viewer.isApplying)
                Positioned(
                  left: 0,
                  right: 0,
                  top: 10,
                  child: Align(
                    alignment: Alignment.topCenter,
                    child: Transform.translate(
                      offset: viewer.pillOffset,
                      child: DonePill(viewer: viewer),
                    ),
                  ),
                ),
            ],
            if (workspace.busy)
              Positioned(
                left: 0,
                right: 0,
                bottom: 64,
                child: Center(child: _StagePill(workspace: workspace)),
              ),
          ],
        );
      },
    );
  }

  int _pageNumber(WorkspaceState workspace, String pageId) {
    final index = workspace.pages.indexWhere((page) => page.id == pageId);
    return index < 0 ? 1 : index + 1;
  }

  bool _hasNeighbor(int delta) {
    final index = workspace.pages.indexWhere(
      (page) => page.id == workspace.activeId,
    );
    final next = index < 0 ? 0 : index + delta;
    return next >= 0 && next < workspace.pages.length;
  }
}

class _Marks extends StatelessWidget {
  const _Marks({
    required this.pageName,
    required this.pageNumber,
    required this.regions,
    required this.overflow,
    required this.palette,
  });

  final String pageName;
  final int pageNumber;
  final int regions;
  final int overflow;
  final IltPalette palette;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final number = pageNumber.toString().padLeft(2, '0');
    return Row(
      children: [
        _chip(
          theme,
          palette,
          '$number · $pageName',
          Icons.insert_drive_file_outlined,
        ),
        const SizedBox(width: 6),
        _chip(theme, palette, 'Регионов: $regions', null, ghost: true),
        if (overflow > 0) ...[
          const SizedBox(width: 6),
          _chip(
            theme,
            palette,
            '$overflow не влезает',
            Icons.warning_amber_outlined,
            warn: true,
          ),
        ],
      ],
    );
  }

  Widget _chip(
    ThemeData theme,
    IltPalette palette,
    String text,
    IconData? icon, {
    bool ghost = false,
    bool warn = false,
  }) {
    final color = warn ? palette.textWarning : palette.textPrimary;
    return Container(
      key: Key('viewer-mark-$text'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: ghost
            ? palette.surface2.withValues(alpha: 0.7)
            : palette.surface2.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: warn ? palette.textWarning.withValues(alpha: 0.5) : palette.border,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: color),
            const SizedBox(width: 5),
          ],
          Text(
            text,
            style: theme.textTheme.labelSmall?.copyWith(color: color),
          ),
        ],
      ),
    );
  }
}

class _NavArrow extends StatelessWidget {
  const _NavArrow({
    required this.alignment,
    required this.keyName,
    required this.icon,
    required this.onTap,
  });

  final Alignment alignment;
  final String keyName;
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Align(
      alignment: alignment,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6),
        child: Material(
          color: palette.surface2.withValues(alpha: 0.85),
          shape: const CircleBorder(),
          child: IconButton(
            key: Key(keyName),
            tooltip: alignment == Alignment.centerLeft
                ? 'Предыдущая (PgUp)'
                : 'Следующая (PgDn)',
            onPressed: onTap,
            icon: Icon(icon, size: 20),
            color: onTap == null ? palette.textMuted : palette.textPrimary,
          ),
        ),
      ),
    );
  }
}

/// Пилюля этапа прогона над канвасом (как в 022).
class _StagePill extends StatelessWidget {
  const _StagePill({required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final running = workspace.pages.where((page) => page.isRunning).toList();
    final runningPage = running.isEmpty ? null : running.first;
    final stage = workspace.paused
        ? 'Пауза'
        : (runningPage == null
            ? 'Подготовка'
            : (stageLabel(runningPage.stage).isEmpty
                ? 'Обработка'
                : stageLabel(runningPage.stage)));
    final progress = runningPage?.progress ?? workspace.jobPercent;
    return Container(
      key: const Key('scene-stage-pill'),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: palette.surface2,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: palette.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x55000000),
            blurRadius: 14,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (workspace.paused)
            Icon(Icons.pause, size: 14, color: palette.textWarning)
          else
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                value: progress > 0 ? progress / 100 : null,
                color: palette.primary,
              ),
            ),
          const SizedBox(width: 8),
          Text(
            '$stage · $progress %',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: palette.textPrimary),
          ),
        ],
      ),
    );
  }
}
