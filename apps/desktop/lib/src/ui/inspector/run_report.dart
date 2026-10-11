import 'package:flutter/material.dart';

import '../../state/workspace_state.dart';
import '../theme.dart';
import 'inspector_controls.dart';

/// Вкладка «Отчёт»: итоги прогона, ошибки и чек-лист после прогона.
class RunReport extends StatefulWidget {
  const RunReport({super.key, required this.workspace, this.onOpenLog});

  final WorkspaceState workspace;
  final VoidCallback? onOpenLog;

  @override
  State<RunReport> createState() => _RunReportState();
}

class _RunReportState extends State<RunReport> {
  final Set<int> _checked = {0};

  static const _checklist = [
    'Проверить страницы «Не влез»',
    'Просмотреть заменённые звуки',
    'Экспорт в translated/',
  ];

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final workspace = widget.workspace;
    final batch = workspace.batch;
    PageRow? problem;
    for (final page in workspace.pages) {
      if (page.isProblem) {
        problem = page;
        break;
      }
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 12),
      children: [
        if (workspace.paused)
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Align(
              alignment: Alignment.centerLeft,
              child: InspectorChip('Пауза', tone: 'warn'),
            ),
          ),
        _row(theme, palette, 'Всего страниц', '${batch.total}'),
        _row(theme, palette, 'Готово', '${batch.finished}'),
        _row(theme, palette, 'Ошибки', '${batch.errors}'),
        _row(theme, palette, 'Без LLM', '${batch.offline}'),
        _row(theme, palette, 'В очереди', '${batch.queued}'),
        _row(theme, palette, 'Идёт', '${batch.running}'),
        if (problem != null) ...[
          const SizedBox(height: 8),
          Container(
            key: const Key('report-error-banner'),
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: palette.textError.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: palette.textError.withValues(alpha: 0.4),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${problem.name}: ${problem.error}',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: palette.textError),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 4,
                  children: [
                    InspectorAction(
                      key: const Key('report-retry'),
                      label: 'Повторить ошибки',
                      icon: Icons.replay,
                      onPressed: workspace.retryErrors,
                    ),
                    InspectorAction(
                      key: const Key('report-open-log'),
                      label: 'Открыть лог',
                      icon: Icons.description_outlined,
                      onPressed: widget.onOpenLog,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 12),
        Text(
          'Чек-лист после прогона',
          style: theme.textTheme.labelMedium,
        ),
        for (var i = 0; i < _checklist.length; i++)
          InkWell(
            key: Key('report-check-$i'),
            onTap: () => setState(() {
              if (!_checked.remove(i)) _checked.add(i);
            }),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  SizedBox(
                    width: 30,
                    height: 24,
                    child: Checkbox(
                      value: _checked.contains(i),
                      onChanged: (value) => setState(() {
                        if (value == true) {
                          _checked.add(i);
                        } else {
                          _checked.remove(i);
                        }
                      }),
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      _checklist[i],
                      style: theme.textTheme.labelSmall,
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  Widget _row(
    ThemeData theme,
    IltPalette palette,
    String label,
    String value,
  ) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(child: Text(label, style: theme.textTheme.labelSmall)),
          Text(
            value,
            style: theme.textTheme.bodySmall
                ?.copyWith(color: palette.textPrimary),
          ),
        ],
      ),
    );
  }
}
