import 'dart:async';

import 'package:flutter/material.dart';

import '../../state/secondary_state.dart';
import '../../state/shell_state.dart';
import '../theme.dart';

/// Экран глоссария серии: таблица с инлайн-правкой и сохранением.
class GlossaryScreen extends StatefulWidget {
  const GlossaryScreen({super.key, required this.state});

  final ShellState state;

  @override
  State<GlossaryScreen> createState() => _GlossaryScreenState();
}

class _GlossaryScreenState extends State<GlossaryScreen> {
  List<GlossaryRow> _rows = const [];
  String _query = '';
  int? _editing;
  bool _dirty = false;
  bool _loaded = false;

  final TextEditingController _source = TextEditingController();
  final TextEditingController _target = TextEditingController();
  final TextEditingController _note = TextEditingController();
  String _gender = '';

  ShellState get state => widget.state;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _source.dispose();
    _target.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    await state.secondary.loadGlossary();
    if (!mounted) return;
    setState(() {
      _rows = List.of(state.secondary.glossary);
      _loaded = true;
      _dirty = false;
      _editing = null;
    });
  }

  void _startEdit(int index) {
    final row = _rows[index];
    _source.text = row.source;
    _target.text = row.target;
    _note.text = row.note;
    _gender = row.gender;
    setState(() => _editing = index);
  }

  void _commitEdit() {
    final index = _editing;
    if (index == null) return;
    setState(() {
      _rows[index] = GlossaryRow(
        source: _source.text.trim(),
        target: _target.text,
        gender: _gender,
        note: _note.text,
      );
      _editing = null;
      _dirty = true;
    });
  }

  void _addRow() {
    setState(() {
      _rows = [..._rows, const GlossaryRow()];
      _editing = _rows.length - 1;
      _source.text = '';
      _target.text = '';
      _note.text = '';
      _gender = '';
      _dirty = true;
    });
  }

  void _removeRow(int index) {
    setState(() {
      _rows = [..._rows]..removeAt(index);
      if (_editing == index) _editing = null;
      _dirty = true;
    });
  }

  Future<void> _save() async {
    if (_editing != null) _commitEdit();
    await state.secondary.saveGlossary(_rows);
    if (!mounted) return;
    setState(() {
      _rows = List.of(state.secondary.glossary);
      _dirty = false;
      _editing = null;
    });
    final error = state.secondary.errorText;
    if (error == null) _toast('Глоссарий сохранён');
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  List<(int, GlossaryRow)> get _visible {
    final text = _query.trim().toLowerCase();
    return [
      for (var index = 0; index < _rows.length; index++)
        if (text.isEmpty ||
            _rows[index].source.toLowerCase().contains(text) ||
            _rows[index].target.toLowerCase().contains(text) ||
            _rows[index].note.toLowerCase().contains(text))
          (index, _rows[index]),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => Container(
        key: const Key('glossary-screen'),
        color: palette.bgPrimary,
        child: Column(
          children: [
            Container(
              height: 46,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(bottom: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  Icon(Icons.menu_book_outlined, size: 16, color: palette.primary),
                  const SizedBox(width: 8),
                  Text('Глоссарий', style: theme.textTheme.titleSmall),
                  const SizedBox(width: 12),
                  Text(
                    '${_rows.length} ${_recordsWord(_rows.length)} · единый для серии',
                    style: theme.textTheme.labelSmall,
                  ),
                  const Spacer(),
                  SizedBox(
                    width: 260,
                    child: SizedBox(
                      height: kFieldHeight,
                      child: TextField(
                        key: const Key('glossary-search'),
                        style: theme.textTheme.bodySmall,
                        textAlignVertical: TextAlignVertical.center,
                        decoration: const InputDecoration(
                          isDense: true,
                          hintText: 'Поиск: имя, термин…',
                          contentPadding: EdgeInsets.symmetric(horizontal: 8),
                        ),
                        onChanged: (value) => setState(() => _query = value),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    key: const Key('glossary-close'),
                    tooltip: 'Закрыть (Esc)',
                    iconSize: 16,
                    onPressed: () => state.closeOverlay(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Expanded(
              child: !_loaded
                  ? const Center(child: CircularProgressIndicator())
                  : _rows.isEmpty
                      ? Center(
                          child: Text(
                            'Пока пусто — добавьте строку',
                            key: const Key('glossary-empty'),
                            style: theme.textTheme.bodySmall,
                          ),
                        )
                      : ListView(
                          key: const Key('glossary-list'),
                          padding: const EdgeInsets.all(12),
                          children: [
                            _header(context),
                            for (final (index, row) in _visible)
                              _rowWidget(context, index, row),
                          ],
                        ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(top: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  OutlinedButton(
                    key: const Key('glossary-add'),
                    onPressed: _addRow,
                    child: const Text('Добавить строку'),
                  ),
                  const Spacer(),
                  Text(
                    'Совпадения не зависят от регистра',
                    style: theme.textTheme.labelSmall,
                  ),
                  const SizedBox(width: 12),
                  FilledButton(
                    key: const Key('glossary-save'),
                    onPressed: _dirty && !state.secondary.glossaryLoading
                        ? _save
                        : null,
                    child: const Text('Сохранить'),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    key: const Key('glossary-done'),
                    onPressed: () => state.closeOverlay(),
                    child: const Text('Готово'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context) {
    final theme = Theme.of(context);
    final style = theme.textTheme.labelSmall
        ?.copyWith(fontWeight: FontWeight.w600);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
      child: Row(
        children: [
          Expanded(flex: 3, child: Text('Оригинал', style: style)),
          Expanded(flex: 3, child: Text('Перевод', style: style)),
          SizedBox(width: 70, child: Text('Род', style: style)),
          Expanded(flex: 4, child: Text('Заметка на серию', style: style)),
          const SizedBox(width: 76),
        ],
      ),
    );
  }

  Widget _rowWidget(BuildContext context, int index, GlossaryRow row) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final editing = _editing == index;
    return Container(
      key: Key('glossary-row-$index'),
      margin: const EdgeInsets.only(bottom: 4),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: editing ? palette.surface2 : palette.surface1,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: editing ? palette.primary : palette.line),
      ),
      child: editing
          ? Row(
              children: [
                Expanded(
                  flex: 3,
                  child: IltSmallField(controller: _source, hint: 'Оригинал'),
                ),
                const SizedBox(width: 6),
                Expanded(
                  flex: 3,
                  child: IltSmallField(controller: _target, hint: 'Перевод'),
                ),
                const SizedBox(width: 6),
                SizedBox(
                  width: 64,
                  child: DropdownButtonFormField<String>(
                    initialValue: _gender,
                    isDense: true,
                    style: theme.textTheme.labelSmall,
                    dropdownColor: palette.surface2,
                    items: const [
                      DropdownMenuItem(value: '', child: Text('—')),
                      DropdownMenuItem(value: 'm', child: Text('м')),
                      DropdownMenuItem(value: 'f', child: Text('ж')),
                      DropdownMenuItem(value: 'n', child: Text('ср')),
                    ],
                    onChanged: (value) => _gender = value ?? '',
                  ),
                ),
                const SizedBox(width: 6),
                Expanded(
                  flex: 4,
                  child: IltSmallField(controller: _note, hint: 'Заметка'),
                ),
                const SizedBox(width: 6),
                FilledButton(
                  key: const Key('glossary-commit'),
                  onPressed: _commitEdit,
                  child: const Text('ОК'),
                ),
              ],
            )
          : Row(
              children: [
                Expanded(
                  flex: 3,
                  child: Text(
                    row.source,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: palette.textPrimary),
                  ),
                ),
                Expanded(
                  flex: 3,
                  child: Text(
                    row.target,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                SizedBox(
                  width: 70,
                  child: Text(
                    _genderLabel(row.gender),
                    style: theme.textTheme.labelSmall,
                  ),
                ),
                Expanded(
                  flex: 4,
                  child: Text(
                    row.note,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelSmall,
                  ),
                ),
                IconButton(
                  key: Key('glossary-edit-$index'),
                  tooltip: 'Изменить',
                  iconSize: 14,
                  onPressed: () => _startEdit(index),
                  icon: const Icon(Icons.edit_outlined),
                ),
                IconButton(
                  key: Key('glossary-delete-$index'),
                  tooltip: 'Удалить',
                  iconSize: 14,
                  onPressed: () => _removeRow(index),
                  icon: Icon(Icons.delete_outline, color: palette.textError),
                ),
              ],
            ),
    );
  }

  static String _genderLabel(String value) {
    switch (value) {
      case 'm':
        return 'м';
      case 'f':
        return 'ж';
      case 'n':
        return 'ср';
      default:
        return '—';
    }
  }

  static String _recordsWord(int count) {
    final abs = count.abs() % 100;
    final last = abs % 10;
    if (abs > 10 && abs < 20) return 'записей';
    if (last == 1) return 'запись';
    if (last >= 2 && last <= 4) return 'записи';
    return 'записей';
  }
}

/// Мелкое поле для инлайн-правки строки.
class IltSmallField extends StatelessWidget {
  const IltSmallField({super.key, required this.controller, this.hint});

  final TextEditingController controller;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return SizedBox(
      height: kFieldHeight,
      child: TextField(
        controller: controller,
        style: Theme.of(context).textTheme.bodySmall,
        textAlignVertical: TextAlignVertical.center,
        decoration: InputDecoration(
          isDense: true,
          hintText: hint,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8),
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
      ),
    );
  }
}
