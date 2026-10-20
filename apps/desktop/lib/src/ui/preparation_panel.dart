import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:file_selector/file_selector.dart';

import '../state/secondary_state.dart';
import 'file_dialogs.dart';

/// Единая подготовка в мастере и настройках; технические паки скрыты в дополнительных настройках.
class PreparationPanel extends StatefulWidget {
  const PreparationPanel({super.key, required this.state, required this.selection, this.onDeviceChanged});

  final SecondaryState state;
  final Map<String, dynamic> selection;
  final ValueChanged<String>? onDeviceChanged;

  @override
  State<PreparationPanel> createState() => _PreparationPanelState();
}

class _PreparationPanelState extends State<PreparationPanel> {
  bool _cpu = false;
  String _lastSelection = '';

  Map<String, dynamic> get selection => {
        for (final key in const ['source_lang', 'target_lang', 'translator_backend', 'inpainter_backend', 'models_dir'])
          if (widget.selection.containsKey(key)) key: widget.selection[key],
        'device': _cpu ? 'cpu' : (widget.selection['device'] == 'cuda' ? 'cuda' : 'auto'),
      };

  @override
  void initState() {
    super.initState();
    _cpu = widget.selection['device'] == 'cpu';
    unawaited(widget.state.refreshPreparation());
    _preview();
  }

  void _preview() {
    _lastSelection = jsonEncode(selection);
    unawaited(widget.state.previewPreparation(selection));
  }

  @override
  void didUpdateWidget(covariant PreparationPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (jsonEncode(selection) != _lastSelection) _preview();
  }

  String bytes(num value) => value >= 1000000000
      ? '${(value / 1000000000).toStringAsFixed(2)} ГБ'
      : '${(value / 1000000).toStringAsFixed(1)} МБ';

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.state,
      builder: (context, _) {
        final state = widget.state;
        final snapshot = state.preparation;
        final stage = '${snapshot['state'] ?? 'idle'}';
        final busy = ['planning', 'downloading', 'checking', 'installing'].contains(stage);
        final active = busy || stage == 'paused' || stage == 'error';
        final view = active ? snapshot : state.preparationPlan;
        final total = (view['total'] as num?) ?? 0;
        final done = (snapshot['done'] as num?) ?? 0;
        final ready = !active && view['state'] == 'ready';
        final labels = {
          'planning': 'Подготовка',
          'downloading': 'Загрузка',
          'checking': 'Проверка',
          'installing': 'Установка',
          'paused': 'Загрузка приостановлена',
          'error': 'Подготовка остановлена',
          'ready': 'Приложение подготовлено',
        };
        return Material(type: MaterialType.transparency, child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Подготовка приложения', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(ready ? 'Нужные компоненты уже установлены.' : view.isEmpty ? 'Проверяем список компонентов…'
                : total == 0 ? 'Файлы уже на диске: осталось проверить компоненты.' : 'Нужно скачать: ${bytes(total)}'),
            if (!ready && view['required_space'] is num)
              Text('Свободное место: примерно ${bytes(view['required_space'] as num)}'),
            if (!active)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Меньше загрузка, медленнее обработка'),
                subtitle: const Text('Использовать процессор без ускорения NVIDIA'),
                value: _cpu,
                onChanged: (value) {
                  setState(() => _cpu = value ?? false);
                  widget.onDeviceChanged?.call(_cpu ? 'cpu' : 'auto');
                  _preview();
                },
              ),
            for (final warning in (view['warnings'] as List? ?? const [])) Text('$warning'),
            if (active) ...[
              const SizedBox(height: 12),
              Text(labels[stage] ?? stage),
              if ('${snapshot['current'] ?? ''}'.isNotEmpty) Text('${snapshot['current']}'),
              if (busy || stage == 'paused') ...[
                const SizedBox(height: 6),
                LinearProgressIndicator(value: total > 0 ? (done / total).clamp(0.0, 1.0) : null),
                if (total > 0) Text('${bytes(done)} / ${bytes(total)}'),
              ],
              if ('${snapshot['error'] ?? ''}'.isNotEmpty)
                Text('${snapshot['error']}', style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            if ((state.errorText ?? '').isNotEmpty)
              Text(state.errorText!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (!busy)
                  TextButton(
                    onPressed: () async {
                      final data = await state.api?.getJson('/api/preparation/diagnostics');
                      if (data == null) return;
                      final location = await getSaveLocation(suggestedName: 'ilt-diagnostics.json');
                      if (location != null) {
                        await XFile.fromData(utf8.encode(const JsonEncoder.withIndent('  ').convert(data)),
                            mimeType: 'application/json', name: 'ilt-diagnostics.json').saveTo(location.path);
                      }
                    },
                    child: const Text('Сохранить диагностику'),
                  ),
                if (!busy)
                  TextButton(
                    key: const Key('preparation-verify'),
                    onPressed: () => state.verifyPreparation(selection),
                    child: const Text('Проверить и восстановить'),
                  ),
                if (busy)
                  OutlinedButton(
                    key: const Key('preparation-pause'),
                    onPressed: state.pausePreparation,
                    child: const Text('Приостановить'),
                  )
                else if (stage == 'paused' || stage == 'error') ...[
                  FilledButton(
                    key: const Key('preparation-resume'),
                    onPressed: state.resumePreparation,
                    child: const Text('Продолжить'),
                  ),
                  if (snapshot['error_kind'] == 'compatibility')
                    OutlinedButton(
                      onPressed: () => state.startPreparation({...widget.selection, 'device': 'cpu'}),
                      child: const Text('Использовать CPU'),
                    ),
                  OutlinedButton(
                    onPressed: () => state.startPreparation(selection),
                    child: const Text('Подготовить заново'),
                  ),
                  if (snapshot['error_kind'] == 'disk' || snapshot['error_kind'] == 'permission')
                    OutlinedButton(
                      onPressed: () async {
                        final folder = await pickFolder();
                        if (folder != null) await state.changeComponentLocation(folder);
                      },
                      child: const Text('Выбрать папку'),
                    ),
                ] else if (!ready)
                  FilledButton(
                    key: const Key('preparation-start'),
                    onPressed: view.isEmpty ? null : () => state.startPreparation(selection),
                    child: const Text('Подготовить приложение'),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            const Text('Можно закрыть приложение: скачанные данные сохранятся, загрузку можно продолжить.'),
          ],
        ));
      },
    );
  }
}
