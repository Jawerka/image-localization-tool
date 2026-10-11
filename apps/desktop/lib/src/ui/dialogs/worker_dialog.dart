import 'package:flutter/material.dart';

import '../theme.dart';

/// Действие пользователя в диалоге ошибки воркера.
enum WorkerChoice { retry, openLog, close }

/// Ошибка обработки: воркер перезапускался слишком часто.
class WorkerDialog extends StatelessWidget {
  const WorkerDialog({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AlertDialog(
      key: const Key('worker-dialog'),
      backgroundColor: palette.bgPrimary,
      title: Text(
        'Не удалось запустить обработку',
        style: theme.textTheme.titleSmall,
      ),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: palette.textError.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(
                  color: palette.textError.withValues(alpha: 0.4),
                ),
              ),
              child: Text(message, style: theme.textTheme.bodySmall),
            ),
            const SizedBox(height: 10),
            Text(
              'Готовые страницы не пострадали. Повторная ошибка возможна, '
              'если не исправлена причина.',
              style: theme.textTheme.labelSmall,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          key: const Key('worker-close'),
          onPressed: () => Navigator.of(context).pop(WorkerChoice.close),
          child: const Text('Закрыть'),
        ),
        OutlinedButton(
          key: const Key('worker-open-log'),
          onPressed: () => Navigator.of(context).pop(WorkerChoice.openLog),
          child: const Text('Открыть лог'),
        ),
        FilledButton(
          key: const Key('worker-retry'),
          onPressed: () => Navigator.of(context).pop(WorkerChoice.retry),
          child: const Text('Повторить ошибки'),
        ),
      ],
    );
  }
}
