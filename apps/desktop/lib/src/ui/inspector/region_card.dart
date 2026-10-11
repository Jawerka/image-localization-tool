import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import '../widgets.dart';
import 'inspector_controls.dart';
import 'region_style_section.dart';
import 'sfx_section.dart';

/// Типы регионов (подписи — как `TYPES` в `web/js/inspector.js`).
const List<(String, String)> regionTypes = [
  ('dialogue', 'диалог'),
  ('narration', 'рассказ'),
  ('title', 'заголовок'),
  ('sfx', 'звук'),
  ('thought', 'мысль'),
  ('caption', 'надпись'),
];

String regionTypeLabel(String type) {
  for (final (value, label) in regionTypes) {
    if (value == type) return label;
  }
  return type;
}

/// Карточка региона: свёрнутая — строка превью, выбранная — развёрнута (024).
class RegionCard extends StatefulWidget {
  const RegionCard({
    super.key,
    required this.viewer,
    required this.region,
    required this.index,
    required this.selected,
  });

  final ViewerState viewer;
  final Region region;
  final int index;
  final bool selected;

  @override
  State<RegionCard> createState() => _RegionCardState();
}

class _RegionCardState extends State<RegionCard> {
  final _translation = TextEditingController();
  final _translationFocus = FocusNode();
  final _original = TextEditingController();
  final _originalFocus = FocusNode();
  final _speaker = TextEditingController();
  final _speakerFocus = FocusNode();

  Region get _region => widget.region;
  ViewerState get _viewer => widget.viewer;
  String get _id => _region.id;

  @override
  void dispose() {
    _translation.dispose();
    _translationFocus.dispose();
    _original.dispose();
    _originalFocus.dispose();
    _speaker.dispose();
    _speakerFocus.dispose();
    super.dispose();
  }

  void _sync(TextEditingController controller, String value, FocusNode node) {
    if (node.hasFocus) return;
    if (controller.text != value) controller.text = value;
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final region = _region;
    final selected = widget.selected;
    final title = '${region.data['text'] ?? ''}'.trim().isNotEmpty
        ? '${region.data['text']}'
        : ('${region.data['translation'] ?? ''}'.trim().isNotEmpty
            ? '${region.data['translation']}'
            : 'Пустой регион');
    final borderColor = selected
        ? palette.primary
        : region.overflow
            ? palette.textWarning.withValues(alpha: 0.7)
            : palette.line;

    _sync(_translation, '${region.data['translation'] ?? ''}', _translationFocus);
    _sync(_original, '${region.data['text'] ?? ''}', _originalFocus);
    _sync(_speaker, '${region.data['speaker'] ?? ''}', _speakerFocus);

    return Container(
      key: Key('region-card-$_id'),
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(
        color: selected ? palette.surface2 : palette.surface1,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: borderColor, width: selected ? 1.4 : 1),
      ),
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            key: Key('region-card-head-$_id'),
            onTap: () => _viewer.selectRegion(_id),
            child: Row(
              children: [
                Container(
                  width: 20,
                  height: 20,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: selected ? palette.primary : palette.surface3,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    '${widget.index + 1}',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: selected ? palette.primaryFg : palette.textMuted,
                    ),
                  ),
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelMedium,
                  ),
                ),
                if (region.skip) ...[
                  const SizedBox(width: 4),
                  const InspectorChip('Пропущен'),
                ],
                if (region.overflow) ...[
                  const SizedBox(width: 4),
                  const InspectorChip('Не влез', tone: 'warn'),
                ],
                if (region.isSfx) ...[
                  const SizedBox(width: 4),
                  const InspectorChip('Звук', tone: 'bad'),
                ],
              ],
            ),
          ),
          if (!selected) ...[
            Padding(
              padding: const EdgeInsets.only(left: 27, top: 3),
              child: Text(
                _previewLine(region),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodySmall,
              ),
            ),
          ] else ...[
            const SizedBox(height: 6),
            if (_viewer.isActionPending(_id))
              Row(
                children: [
                  const SizedBox(
                    width: 12,
                    height: 12,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: 6),
                  Text('Ждёт сервер LLM', style: theme.textTheme.labelSmall),
                ],
              ),
            InspectorField(
              label: 'Перевод',
              trailing: _saveChip(palette, theme),
              child: InspectorInput(
                key: Key('region-translation-$_id'),
                controller: _translation,
                focusNode: _translationFocus,
                minLines: 2,
                maxLines: 6,
                onChanged: (value) => _viewer.setRegionTranslation(_id, value),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                '${_translation.text.length} зн.',
                style: theme.textTheme.labelSmall,
              ),
            ),
            Disclosure(
              title: 'Оригинал',
              child: InspectorInput(
                key: Key('region-original-$_id'),
                controller: _original,
                focusNode: _originalFocus,
                minLines: 2,
                maxLines: 6,
                onChanged: (value) => _viewer.setRegionText(_id, value),
              ),
            ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: InspectorField(
                    label: 'Тип',
                    child: IltSelect(
                      value: region.type,
                      options: _typeOptions(region.type),
                      onChanged: (value) => _viewer.setRegionType(_id, value),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: InspectorField(
                    label: 'Говорящий',
                    child: InspectorInput(
                      key: Key('region-speaker-$_id'),
                      controller: _speaker,
                      focusNode: _speakerFocus,
                      onChanged: (value) =>
                          _viewer.setRegionSpeaker(_id, value),
                    ),
                  ),
                ),
              ],
            ),
            if (region.isSfx) SfxSection(viewer: _viewer, region: region),
            const SizedBox(height: 4),
            _actions(context),
            const SizedBox(height: 6),
            _nudgePad(theme, palette),
            const SizedBox(height: 4),
            Disclosure(
              title: 'Стиль',
              initiallyExpanded: true,
              child: RegionStyleSection(viewer: _viewer, region: region),
            ),
          ],
        ],
      ),
    );
  }

  Widget _saveChip(IltPalette palette, ThemeData theme) {
    final pageId = _viewer.pageId;
    final dirty = pageId != null && _viewer.isDirty(pageId);
    if (_viewer.hasDeferredDraft) return const InspectorChip('В черновике');
    if (dirty) return const InspectorChip('Сохраняем…', tone: 'warn');
    return const InspectorChip('Автосохранено', tone: 'ok');
  }

  String _previewLine(Region region) {
    final parts = [
      '${region.data['translation'] ?? ''}'.trim(),
      regionTypeLabel(region.type),
      '${region.data['speaker'] ?? ''}'.trim(),
    ].where((item) => item.isNotEmpty);
    return parts.join(' · ');
  }

  List<(String, String)> _typeOptions(String current) {
    final options = regionTypes.toList();
    if (!options.any((item) => item.$1 == current)) {
      options.add((current, current));
    }
    return options;
  }

  Widget _actions(BuildContext context) {
    final viewer = _viewer;
    final busy = viewer.actionPending;
    return Wrap(
      spacing: 4,
      runSpacing: 4,
      children: [
        InspectorAction(
          key: Key('region-recognize-$_id'),
          label: 'Распознать',
          icon: Icons.auto_fix_high,
          busy: viewer.isActionPending(_id),
          onPressed: busy ? null : () => viewer.regionAction(_id, 'recognize'),
        ),
        InspectorAction(
          key: Key('region-retranslate-$_id'),
          label: 'Перевести заново',
          icon: Icons.translate,
          onPressed: busy ? null : () => viewer.regionAction(_id, 'retranslate'),
        ),
        InspectorAction(
          key: Key('region-shorten-$_id'),
          label: 'Сократить',
          icon: Icons.compress,
          onPressed: busy ? null : () => viewer.regionAction(_id, 'shorten'),
        ),
        InspectorAction(
          key: Key('region-skip-$_id'),
          label: 'Не переводить',
          icon: Icons.block,
          active: _region.skip,
          onPressed: () => viewer.toggleRegionSkip(_id),
        ),
        InspectorAction(
          key: Key('region-reset-style-$_id'),
          label: 'Сбросить стили',
          icon: Icons.refresh,
          onPressed: () => viewer.resetRegionStyle(_id),
        ),
        InspectorAction(
          key: Key('region-delete-$_id'),
          label: 'Удалить',
          icon: Icons.delete_outline,
          danger: true,
          onPressed: () => viewer.deleteRegion(_id),
        ),
      ],
    );
  }

  Widget _nudgePad(ThemeData theme, IltPalette palette) {
    Widget cell(String direction, IconData icon, String tooltip) {
      return Tooltip(
        message: '$tooltip (Shift: 10px)',
        child: InkWell(
          key: Key('region-nudge-$direction-$_id'),
          onTap: () => _viewer.nudgeSelectedRegion(
            direction,
            shift: HardwareKeyboard.instance.isShiftPressed,
          ),
          child: SizedBox(
            width: 26,
            height: 22,
            child: Icon(icon, size: 15, color: palette.textMuted),
          ),
        ),
      );
    }

    return Row(
      children: [
        Text('Позиция ', style: theme.textTheme.labelSmall),
        Expanded(
          child: Align(
            alignment: Alignment.centerLeft,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SizedBox(width: 26),
                    cell('up', Icons.keyboard_arrow_up, 'Вверх'),
                    const SizedBox(width: 26),
                  ],
                ),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    cell('left', Icons.keyboard_arrow_left, 'Влево'),
                    const SizedBox(width: 26),
                    cell('right', Icons.keyboard_arrow_right, 'Вправо'),
                  ],
                ),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SizedBox(width: 26),
                    cell('down', Icons.keyboard_arrow_down, 'Вниз'),
                    const SizedBox(width: 26),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
