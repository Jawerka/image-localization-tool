import 'package:flutter/material.dart';

import '../../state/workspace_state.dart';
import '../labels.dart';
import '../theme.dart';
import 'inspector_controls.dart';

/// Вкладка «Страница»: факты документа, тайминги, предупреждения и действия.
class PageFacts extends StatelessWidget {
  const PageFacts({super.key, required this.workspace});

  final WorkspaceState workspace;

  @override
  Widget build(BuildContext context) {
    final viewer = workspace.viewer;
    final page = workspace.activePage;
    if (page == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Text(
            'Нет открытой страницы.',
            key: const Key('inspector-page-empty'),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      );
    }
    final document = viewer.document;
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final rows = <(String, String)>[
      ('Статус', pageStatusText(page)),
      ('OCR', '${document?.data['ocr_engine'] ?? ''}'.trim().isEmpty
          ? '—'
          : '${document!.data['ocr_engine']}'),
      ('Перевод', '${document?.data['translator_engine'] ?? ''}'.trim().isEmpty
          ? '—'
          : '${document!.data['translator_engine']}'),
      ('Очистка', _cleanLabel('${workspace.effective('inpainter_backend')}')),
      ('Устройство', workspace.device.isEmpty ? '—' : workspace.device),
    ];
    final timings = document?.data['timings'];
    if (timings is Map) {
      for (final entry in timings.entries) {
        final label = stageLabel('${entry.key}');
        rows.add((label.isEmpty ? '${entry.key}' : label, _formatSeconds(entry.value)));
      }
    }
    final warnings = <String>[
      ...?document?.warnings,
      if (page.error.isNotEmpty) page.error,
    ];

    return ListView(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 12),
      children: [
        for (final (label, value) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 96,
                  child: Text(label, style: theme.textTheme.labelSmall),
                ),
                Expanded(
                  child: Text(
                    value,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: palette.textPrimary),
                  ),
                ),
              ],
            ),
          ),
        for (final warning in warnings)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.warning_amber_outlined,
                    size: 14, color: palette.textWarning),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    warning,
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: palette.textWarning),
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 4,
          runSpacing: 4,
          children: [
            InspectorAction(
              key: const Key('page-retranslate'),
              label: 'Перевести заново',
              icon: Icons.translate,
              onPressed: () => workspace.translate(pageId: page.id),
            ),
            InspectorAction(
              key: const Key('page-reset'),
              label: 'Сбросить правки',
              icon: Icons.restore,
              danger: true,
              onPressed: () => _confirmReset(context),
            ),
          ],
        ),
      ],
    );
  }

  String _cleanLabel(String value) {
    if (value == 'opencv' || value == 'fill') return 'Заливка';
    if (value == 'lama') return 'LaMa';
    return value.isEmpty ? '—' : value;
  }

  String _formatSeconds(Object? value) {
    final number = value is num ? value.toDouble() : double.tryParse('$value');
    if (number == null) return '$value';
    return '${number.toStringAsFixed(1).replaceAll('.', ',')} с';
  }

  Future<void> _confirmReset(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        key: const Key('page-reset-dialog'),
        title: const Text('Сбросить правки?'),
        content: const Text(
          'Ручные правки этой страницы будут заменены результатом пайплайна. '
          'Это нельзя отменить.',
        ),
        actions: [
          TextButton(
            key: const Key('page-reset-cancel'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            key: const Key('page-reset-confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Сбросить'),
          ),
        ],
      ),
    );
    if (ok == true) await workspace.viewer.resetPage();
  }
}
