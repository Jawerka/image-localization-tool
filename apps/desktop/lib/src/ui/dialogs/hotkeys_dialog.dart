import 'package:flutter/material.dart';

import '../theme.dart';

/// Справочник горячих клавиш (F1) с поиском.
class HotkeysDialog extends StatefulWidget {
  const HotkeysDialog({super.key});

  @override
  State<HotkeysDialog> createState() => _HotkeysDialogState();
}

class _HotkeysDialogState extends State<HotkeysDialog> {
  static const groups = [
    (
      'Канвас',
      [
        ('Масштаб', 'Ctrl+колесо'),
        ('Прокрутка', 'Пробел+ЛКМ'),
        ('Вписать', 'Ctrl+0'),
        ('100 %', 'Ctrl+1'),
        ('Кисть / ластик', 'B'),
        ('Лассо', 'P'),
        ('Перевод региона', 'Enter'),
        ('Сдвиг рамки', '↑ ↓ ← →'),
        ('Проблемная страница', 'N'),
      ],
    ),
    (
      'Файл и проект',
      [
        ('Открыть файлы', 'Ctrl+O'),
        ('Сохранить проект', 'Ctrl+S'),
        ('Экспорт', 'Ctrl+E'),
        ('Перевести страницу', 'Ctrl+Enter'),
        ('Перевести всё', 'Ctrl+Shift+Enter'),
        ('Настройки', 'Ctrl+,'),
        ('Горячие клавиши', 'F1'),
        ('Быстрые команды', 'Ctrl+K'),
      ],
    ),
  ];

  String _query = '';

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final text = _query.trim().toLowerCase();
    return AlertDialog(
      key: const Key('hotkeys-dialog'),
      backgroundColor: palette.bgPrimary,
      title: Row(
        children: [
          Text('Горячие клавиши', style: theme.textTheme.titleSmall),
          const SizedBox(width: 16),
          Expanded(
            child: SizedBox(
              height: kFieldHeight,
              child: TextField(
                key: const Key('hotkeys-search'),
                autofocus: true,
                style: theme.textTheme.bodySmall,
                textAlignVertical: TextAlignVertical.center,
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'Поиск по действию…',
                  contentPadding: EdgeInsets.symmetric(horizontal: 8),
                ),
                onChanged: (value) => setState(() => _query = value),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Закрыть (Esc)',
            iconSize: 16,
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.close),
          ),
        ],
      ),
      content: SizedBox(
        width: 540,
        height: 420,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final (title, items) in groups)
                if (_filter(items, text).isNotEmpty) ...[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(0, 10, 0, 4),
                    child: Text(title, style: theme.textTheme.labelMedium),
                  ),
                  for (final (action, keys) in _filter(items, text))
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              action,
                              style: theme.textTheme.bodySmall,
                            ),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: palette.surface2,
                              borderRadius: BorderRadius.circular(4),
                              border: Border.all(color: palette.border),
                            ),
                            child: Text(
                              keys,
                              style: theme.textTheme.labelSmall,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              const SizedBox(height: 12),
              Text(
                'Однобуквенные клавиши не срабатывают в полях ввода и '
                'отключаются в настройках.',
                style: theme.textTheme.labelSmall,
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<(String, String)> _filter(List<(String, String)> items, String text) {
    if (text.isEmpty) return items;
    return [
      for (final item in items)
        if (item.$1.toLowerCase().contains(text) ||
            item.$2.toLowerCase().contains(text))
          item,
    ];
  }
}
