import 'package:flutter/material.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'inspector_controls.dart';

/// Звуковые регионы: вкладка «Текст» — статус и пояснение.
class SfxTextSection extends StatelessWidget {
  const SfxTextSection({super.key, required this.viewer, required this.region});

  final ViewerState viewer;
  final Region region;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final status = viewer.sfxRegionId == region.id ? viewer.sfxStatus : 'idle';

    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const InspectorChip('распознан как звук', tone: 'bad'),
              const SizedBox(width: 6),
              if (status == 'loading')
                Text('Подбираем стиль…', style: theme.textTheme.labelSmall),
            ],
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: palette.surface1,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: palette.line),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, size: 14, color: palette.textMuted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Крупный текст без баллона, 1–2 слова, высокая '
                    'контрастность — типичный SFX. Если это реплика, '
                    'переключите тип на «диалог».',
                    style: theme.textTheme.labelSmall,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 6),
          _otherSfx(context, theme),
        ],
      ),
    );
  }

  Widget _otherSfx(BuildContext context, ThemeData theme) {
    final page = viewer.document;
    if (page == null) return const SizedBox.shrink();
    final others = page.regions
        .where((item) => item.isSfx && item.id != region.id)
        .toList();
    if (others.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Другие звуки страницы', style: theme.textTheme.labelSmall),
        const SizedBox(height: 4),
        for (final item in others)
          TextButton(
            key: Key('sfx-other-${item.id}'),
            onPressed: () => viewer.selectRegion(item.id),
            style: TextButton.styleFrom(
              alignment: Alignment.centerLeft,
              visualDensity: VisualDensity.compact,
              minimumSize: const Size(0, 24),
              padding: const EdgeInsets.symmetric(horizontal: 4),
            ),
            child: Text(
              '${item.data['text'] ?? item.data['translation'] ?? 'Звук'}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.labelSmall,
            ),
          ),
      ],
    );
  }
}

/// Звуковые регионы: вкладка «Шрифт» — подобранный style и повторный подбор.
class SfxFontSection extends StatelessWidget {
  const SfxFontSection({super.key, required this.viewer, required this.region});

  final ViewerState viewer;
  final Region region;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final style = region.data['style'] is Map
        ? (region.data['style'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final family = viewer.fontFamilyFor('${style['font_id'] ?? ''}');
    final rotation = (style['rotation'] as num?)?.toDouble() ?? 0;
    final status = viewer.sfxRegionId == region.id ? viewer.sfxStatus : 'idle';
    final sample = '${region.data['translation'] ?? ''}'.trim().isNotEmpty
        ? '${region.data['translation']}'
        : ('${region.data['text'] ?? ''}'.trim().isNotEmpty
              ? '${region.data['text']}'
              : 'РРРРР!');

    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: palette.surface3,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Подобранный стиль', style: theme.textTheme.labelMedium),
            const SizedBox(height: 4),
            Text(
              sample,
              key: const Key('sfx-style-sample'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 22,
                color: palette.textPrimary,
                fontFamily: family,
              ),
            ),
            const SizedBox(height: 4),
            _kv(theme, palette, 'Шрифт', _fontLabel(style)),
            _kv(
              theme,
              palette,
              'Наклон',
              '${rotation == rotation.roundToDouble() ? rotation.round() : rotation.toStringAsFixed(1)}°',
            ),
            _kv(theme, palette, 'Цвет', rgbToHex(style['fill_rgb'])),
            const SizedBox(height: 6),
            Wrap(
              spacing: 4,
              runSpacing: 4,
              children: [
                InspectorAction(
                  key: const Key('sfx-restyle'),
                  label: 'Подобрать заново',
                  icon: Icons.refresh,
                  busy: status == 'loading',
                  onPressed: status == 'loading'
                      ? null
                      : () => viewer.restyleSfx(region.id),
                ),
                InspectorAction(
                  key: const Key('sfx-select-frame'),
                  label: 'Рамка',
                  icon: Icons.crop_free,
                  onPressed: () => viewer.selectRegion(region.id),
                ),
              ],
            ),
            if (status == 'ready')
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Готово · стиль обновлён',
                  key: const Key('sfx-status'),
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: palette.textSuccess,
                  ),
                ),
              ),
            if (status == 'error')
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  viewer.sfxMessage.isEmpty
                      ? 'Не удалось подобрать стиль'
                      : viewer.sfxMessage,
                  key: const Key('sfx-status'),
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: palette.textError,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _kv(ThemeData theme, IltPalette palette, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(
        children: [
          SizedBox(
            width: 64,
            child: Text(label, style: theme.textTheme.labelSmall),
          ),
          Expanded(
            child: Text(
              value,
              style: theme.textTheme.labelSmall?.copyWith(
                color: palette.textPrimary,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _fontLabel(Map<String, dynamic> style) {
    final id = '${style['font_id'] ?? ''}';
    if (id.isEmpty) return 'по умолчанию';
    for (final font in viewer.fonts) {
      if ('${font['id'] ?? ''}' == id) {
        return '${font['family'] ?? id}';
      }
    }
    return id;
  }
}
