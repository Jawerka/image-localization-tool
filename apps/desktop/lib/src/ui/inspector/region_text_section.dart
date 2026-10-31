import 'package:flutter/material.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../widgets.dart';
import 'inspector_controls.dart';
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

/// Вкладка «Текст»: перевод, оригинал, тип, говорящий и команды LLM.
class RegionTextSection extends StatefulWidget {
  const RegionTextSection({
    super.key,
    required this.viewer,
    required this.region,
  });

  final ViewerState viewer;
  final Region region;

  @override
  State<RegionTextSection> createState() => _RegionTextSectionState();
}

class _RegionTextSectionState extends State<RegionTextSection> {
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
    final theme = Theme.of(context);
    final region = _region;
    _sync(
      _translation,
      '${region.data['translation'] ?? ''}',
      _translationFocus,
    );
    _sync(_original, '${region.data['text'] ?? ''}', _originalFocus);
    _sync(_speaker, '${region.data['speaker'] ?? ''}', _speakerFocus);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_viewer.isActionPending(_id))
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
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
          ),
        InspectorField(
          label: 'Перевод',
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
                  onChanged: (value) => _viewer.setRegionSpeaker(_id, value),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        _actions(),
        if (region.isSfx) SfxTextSection(viewer: _viewer, region: region),
      ],
    );
  }

  List<(String, String)> _typeOptions(String current) {
    final options = regionTypes.toList();
    if (!options.any((item) => item.$1 == current)) {
      options.add((current, current));
    }
    return options;
  }

  Widget _actions() {
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
          onPressed: busy
              ? null
              : () => viewer.regionAction(_id, 'retranslate'),
        ),
        InspectorAction(
          key: Key('region-shorten-$_id'),
          label: 'Сократить',
          icon: Icons.compress,
          onPressed: busy ? null : () => viewer.regionAction(_id, 'shorten'),
        ),
      ],
    );
  }
}
