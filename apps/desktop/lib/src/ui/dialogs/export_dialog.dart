import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';

import '../../state/secondary_state.dart';
import '../../state/shell_state.dart';
import '../../state/workspace_state.dart';
import '../theme.dart';
import '../widgets.dart';

/// Модальный диалог экспорта: область, папка, формат и конфликт имён.
class ExportDialog extends StatefulWidget {
  const ExportDialog({super.key, required this.state});

  final ShellState state;

  @override
  State<ExportDialog> createState() => _ExportDialogState();
}

class _ExportDialogState extends State<ExportDialog> {
  late String _scope = 'ready';
  late String _dest = '';
  late String _format;
  late int _quality;
  late String _conflict;
  bool _openAfter = true;
  bool _busy = false;

  ShellState get state => widget.state;
  WorkspaceState get workspace => widget.state.workspace;

  @override
  void initState() {
    super.initState();
    final settings = workspace.settings;
    _format = '${settings['export_format'] ?? 'png'}';
    final quality = settings['export_jpeg_quality'];
    _quality = quality is num ? quality.toInt() : 90;
    _conflict = '${settings['export_conflict'] ?? 'rename'}';
    if (_scope == 'selected') _scope = 'ready';
  }

  List<PageRow> get _scopePages {
    switch (_scope) {
      case 'all':
        return workspace.pages;
      case 'selected':
        return [
          for (final page in workspace.pages)
            if (workspace.selectedIds.contains(page.id)) page,
        ];
      default:
        return [
          for (final page in workspace.pages)
            if (page.isReady) page,
        ];
    }
  }

  Future<void> _browse() async {
    final path = await getDirectoryPath();
    if (path == null || path.isEmpty) return;
    final ok = await state.secondary.registerExportFolder(path);
    if (ok && mounted) setState(() => _dest = path);
  }

  Future<void> _run() async {
    if (_dest.isEmpty) {
      await _browse();
      if (_dest.isEmpty) return;
    }
    final pages = _scopePages;
    if (pages.isEmpty) return;
    setState(() => _busy = true);
    await state.secondary.runExport(
      ExportOptions(
        pageIds: [for (final page in pages) page.id],
        dest: _dest,
        format: _format,
        jpegQuality: _quality,
        conflict: _conflict,
        openAfter: _openAfter,
      ),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (state.secondary.errorText == null) {
      Navigator.of(context).pop(true);
    }
  }

  String get _summary {
    final count = _scopePages.length;
    final format = _format == 'jpg' ? 'JPG' : 'PNG';
    final conflict = switch (_conflict) {
      'overwrite' => 'перезапись',
      'skip' => 'пропуск',
      _ => 'добавление номера',
    };
    final quality = _format == 'jpg' ? ' · качество $_quality' : '';
    return '$count ${_pagesWord(count)} · $format$quality · конфликты: $conflict';
  }

  static String _pagesWord(int count) {
    final abs = count.abs() % 100;
    final last = abs % 10;
    if (abs > 10 && abs < 20) return 'страниц';
    if (last == 1) return 'страница';
    if (last >= 2 && last <= 4) return 'страницы';
    return 'страниц';
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final allCount = workspace.pages.length;
    final readyCount = _countReady();
    final selectedCount = workspace.selectedIds.length;
    final pages = _scopePages;
    return AlertDialog(
      key: const Key('export-dialog'),
      backgroundColor: palette.bgPrimary,
      title: Row(
        children: [
          Text('Экспорт', style: theme.textTheme.titleSmall),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'Готовые страницы сохраняются в выбранную папку.',
              style: theme.textTheme.labelSmall,
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
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Какие страницы', style: theme.textTheme.bodySmall),
              const SizedBox(height: 6),
              Row(
                children: [
                  Expanded(
                    child: ChoiceCard<String>(
                      value: 'all',
                      selected: _scope,
                      title: 'Все',
                      subtitle: '$allCount ${_pagesWord(allCount)}',
                      enabled: allCount > 0,
                      onChanged: (value) => setState(() => _scope = value),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: ChoiceCard<String>(
                      value: 'ready',
                      selected: _scope,
                      title: 'Только готовые',
                      subtitle: '$readyCount ${_pagesWord(readyCount)}',
                      enabled: readyCount > 0,
                      onChanged: (value) => setState(() => _scope = value),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: ChoiceCard<String>(
                      value: 'selected',
                      selected: _scope,
                      title: 'Выбранные',
                      subtitle:
                          '$selectedCount ${_pagesWord(selectedCount)}',
                      enabled: selectedCount > 0,
                      onChanged: (value) => setState(() => _scope = value),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              FieldRow(
                label: 'Папка',
                width: 360,
                child: Row(
                  children: [
                    Expanded(
                      child: Container(
                        height: kFieldHeight,
                        alignment: Alignment.centerLeft,
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        decoration: BoxDecoration(
                          color: palette.input,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: palette.border),
                        ),
                        child: Text(
                          _dest.isEmpty ? 'не выбрана' : _dest,
                          key: const Key('export-dest'),
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.labelSmall,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton(
                      key: const Key('export-browse'),
                      onPressed: _browse,
                      child: const Text('Обзор…'),
                    ),
                  ],
                ),
              ),
              FieldRow(
                label: 'Формат',
                width: 360,
                child: Row(
                  children: [
                    Expanded(
                      child: IltSelect(
                        value: _format,
                        options: const [('png', 'PNG'), ('jpg', 'JPG')],
                        onChanged: (value) => setState(() => _format = value),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SizedBox(
                      width: 160,
                      child: Row(
                        children: [
                          Text('Качество', style: theme.textTheme.labelSmall),
                          const SizedBox(width: 8),
                          Expanded(
                            child: IltNumberField(
                              value: _quality,
                              min: 1,
                              max: 100,
                              onChanged: _format == 'jpg'
                                  ? (value) => setState(
                                        () => _quality = value.toInt(),
                                      )
                                  : null,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              FieldRow(
                label: 'Совпадение имён',
                width: 360,
                child: IltSelect(
                  value: _conflict,
                  options: const [
                    ('rename', 'Добавить номер (имя-2.jpg)'),
                    ('overwrite', 'Перезаписать'),
                    ('skip', 'Пропустить'),
                  ],
                  onChanged: (value) => setState(() => _conflict = value),
                ),
              ),
              IltSwitchRow(
                label: 'Открыть папку после экспорта',
                value: _openAfter,
                onChanged: (value) => setState(() => _openAfter = value),
              ),
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: palette.surface1,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: palette.line),
                ),
                child: Text(_summary, style: theme.textTheme.labelSmall),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Отмена'),
        ),
        FilledButton(
          key: const Key('export-run'),
          onPressed: _busy || pages.isEmpty ? null : _run,
          child: Text('Экспорт ${pages.length} ${_pagesWord(pages.length)}'),
        ),
      ],
    );
  }

  int _countReady() =>
      workspace.pages.where((page) => page.isReady).length;
}
