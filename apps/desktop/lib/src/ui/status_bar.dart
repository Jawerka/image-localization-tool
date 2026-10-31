import 'package:flutter/material.dart';

import '../state/workspace_state.dart';
import 'labels.dart';
import 'theme.dart';

/// Нижняя строка состояния: сообщение и чипы окружения.
class StatusBar extends StatelessWidget {
  const StatusBar({
    super.key,
    required this.workspace,
    required this.metrics,
  });

  final WorkspaceState workspace;
  final ChromeMetrics metrics;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return Container(
      key: const Key('shell-status-bar'),
      height: metrics.statusBarHeight,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        border: Border(top: BorderSide(color: palette.line)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              _message(),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.labelSmall,
            ),
          ),
          ..._chips(context, palette, theme),
        ],
      ),
    );
  }

  String _message() {
    if (!workspace.hasProject) return 'Проект не открыт';
    if (workspace.paused) {
      final batch = workspace.batch;
      return 'Прогон на паузе · ${batch.finished} из ${batch.total}';
    }
    final running = [
      for (final page in workspace.pages)
        if (page.isRunning) page,
    ];
    if (running.isNotEmpty) {
      final page = running.first;
      final index = workspace.pages.indexOf(page) + 1;
      final stage = stageLabel(page.stage);
      return 'Перевод: страница $index из ${workspace.pages.length}'
          '${stage.isEmpty ? '' : ' · этап «$stage»'}';
    }
    final batch = workspace.batch;
    return 'Готово ${batch.finished} из ${batch.total}';
  }

  List<Widget> _chips(
    BuildContext context,
    IltPalette palette,
    ThemeData theme,
  ) {
    final chips = <String>[];
    final llm = workspace.llm;
    final ok = llm['ok'];
    final models = llm['models'];
    if (ok == true) {
      final count = models is List ? models.length : 0;
      chips.add(count > 0 ? 'LLM · $count ${_modelsWord(count)}' : 'LLM · готов');
    } else if (ok == false) {
      chips.add('LLM · офлайн');
    }
    if (workspace.device.isNotEmpty) chips.add(workspace.device);
    if (!workspace.modelsReady) chips.add('Модели не скачаны');
    if (workspace.version.isNotEmpty) chips.add('v${workspace.version}');
    return [
      for (final chip in chips)
        Padding(
          padding: const EdgeInsets.only(left: 8),
          child: Text(chip, style: theme.textTheme.labelSmall),
        ),
    ];
  }

  static String _modelsWord(int count) {
    final abs = count.abs() % 100;
    final last = abs % 10;
    if (abs > 10 && abs < 20) return 'моделей';
    if (last == 1) return 'модель';
    if (last >= 2 && last <= 4) return 'модели';
    return 'моделей';
  }
}
