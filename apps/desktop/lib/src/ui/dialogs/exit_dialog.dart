import 'package:flutter/material.dart';

import '../theme.dart';

/// Выбор пользователя в диалоге выхода при активном прогоне.
enum ExitChoice { cancel, now, wait }

/// Подтверждение выхода, пока есть незаконченные страницы.
class ExitDialog extends StatefulWidget {
  const ExitDialog({super.key, required this.pages, required this.total});

  final int pages;
  final int total;

  @override
  State<ExitDialog> createState() => _ExitDialogState();
}

class _ExitDialogState extends State<ExitDialog> {
  bool _wait = false;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AlertDialog(
      key: const Key('exit-dialog'),
      backgroundColor: palette.bgPrimary,
      title: Text('Закрыть приложение?', style: theme.textTheme.titleSmall),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Незакончено страниц: ${widget.pages} из ${widget.total}. '
              'Незавершённые останутся в очереди.',
              style: theme.textTheme.bodySmall,
            ),
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: palette.surface1,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: palette.line),
              ),
              child: Text(
                'Прогон остановится на текущем шаге. Уже готовые страницы '
                'сохранятся.',
                style: theme.textTheme.labelSmall,
              ),
            ),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Дождаться окончания и закрыть автоматически',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                Switch(
                  value: _wait,
                  onChanged: (value) => setState(() => _wait = value),
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          key: const Key('exit-cancel'),
          onPressed: () => Navigator.of(context).pop(ExitChoice.cancel),
          child: const Text('Отмена'),
        ),
        FilledButton(
          key: const Key('exit-now'),
          style: FilledButton.styleFrom(backgroundColor: palette.textError),
          onPressed: () => Navigator.of(context).pop(
            _wait ? ExitChoice.wait : ExitChoice.now,
          ),
          child: Text(_wait ? 'Дождаться и выйти' : 'Выйти сейчас'),
        ),
      ],
    );
  }
}
