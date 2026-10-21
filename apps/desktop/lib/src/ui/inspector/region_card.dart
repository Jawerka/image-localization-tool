import 'package:flutter/material.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'inspector_controls.dart';
import 'region_font_section.dart';
import 'region_text_section.dart';
import 'region_transform_section.dart';

/// Вкладки раскрытой карточки региона.
enum RegionTab { text, font, transform }

/// Карточка региона: свёрнутая — строка превью, выбранная — развёрнута (024).
class RegionCard extends StatefulWidget {
  const RegionCard({
    super.key,
    required this.viewer,
    required this.region,
    required this.index,
    required this.selected,
    required this.tab,
    required this.onTabSelected,
  });

  final ViewerState viewer;
  final Region region;
  final int index;
  final bool selected;
  final RegionTab tab;
  final ValueChanged<RegionTab> onTabSelected;

  @override
  State<RegionCard> createState() => _RegionCardState();
}

class _RegionCardState extends State<RegionCard>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(
    length: RegionTab.values.length,
    vsync: this,
    initialIndex: widget.tab.index,
  );

  Region get _region => widget.region;
  ViewerState get _viewer => widget.viewer;
  String get _id => _region.id;

  @override
  void initState() {
    super.initState();
    _prepareLocalIfNeeded();
  }

  @override
  void didUpdateWidget(covariant RegionCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tab != widget.tab && _tabs.index != widget.tab.index) {
      _tabs.index = widget.tab.index;
    }
    if (widget.selected &&
        widget.tab == RegionTab.transform &&
        (!oldWidget.selected || oldWidget.tab != widget.tab)) {
      _prepareLocalIfNeeded();
    }
  }

  void _prepareLocalIfNeeded() {
    if (!widget.selected || widget.tab != RegionTab.transform) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      widget.viewer.prepareLocalPreview(widget.region.id);
    });
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
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
          Padding(
            padding: const EdgeInsets.only(left: 27, top: 3),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _previewLine(region),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
                if (selected) ...[const SizedBox(width: 4), _saveChip()],
              ],
            ),
          ),
          if (selected) ...[
            const SizedBox(height: 6),
            _tabBar(context, palette, theme),
            const SizedBox(height: 4),
            Visibility(
              visible: widget.tab == RegionTab.text,
              maintainState: true,
              child: RegionTextSection(viewer: _viewer, region: region),
            ),
            Visibility(
              visible: widget.tab == RegionTab.font,
              maintainState: true,
              child: RegionFontSection(viewer: _viewer, region: region),
            ),
            Visibility(
              visible: widget.tab == RegionTab.transform,
              maintainState: true,
              child: RegionTransformSection(viewer: _viewer, region: region),
            ),
            const SizedBox(height: 4),
            _footer(),
          ],
        ],
      ),
    );
  }

  Widget _tabBar(BuildContext context, IltPalette palette, ThemeData theme) {
    return Container(
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: palette.line),
      ),
      child: TabBar(
        controller: _tabs,
        onTap: (index) {
          FocusScope.of(context).unfocus();
          widget.onTabSelected(RegionTab.values[index]);
        },
        dividerHeight: 0,
        indicatorSize: TabBarIndicatorSize.tab,
        indicatorPadding: const EdgeInsets.all(1),
        indicator: BoxDecoration(
          color: palette.surface2,
          borderRadius: BorderRadius.circular(5),
        ),
        labelColor: palette.textPrimary,
        unselectedLabelColor: palette.textMuted,
        labelStyle: theme.textTheme.labelSmall,
        unselectedLabelStyle: theme.textTheme.labelSmall,
        overlayColor: const WidgetStatePropertyAll(Colors.transparent),
        padding: EdgeInsets.zero,
        labelPadding: EdgeInsets.zero,
        tabs: [
          Tab(key: Key('region-tab-text-$_id'), height: 30, text: 'Текст'),
          Tab(key: Key('region-tab-font-$_id'), height: 30, text: 'Шрифт'),
          Tab(
            key: Key('region-tab-transform-$_id'),
            height: 30,
            text: 'Трансформация',
          ),
        ],
      ),
    );
  }

  Widget _footer() {
    final busy = _viewer.actionPending;
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(
        children: [
          InspectorAction(
            key: Key('region-skip-$_id'),
            label: 'Не переводить',
            icon: Icons.block,
            active: _region.skip,
            onPressed: () => _viewer.toggleRegionSkip(_id),
          ),
          const Spacer(),
          InspectorAction(
            key: Key('region-delete-$_id'),
            label: 'Удалить',
            icon: Icons.delete_outline,
            danger: true,
            onPressed: busy ? null : () => _viewer.deleteRegion(_id),
          ),
        ],
      ),
    );
  }

  Widget _saveChip() {
    final pageId = _viewer.pageId;
    final dirty = pageId != null && _viewer.isDirty(pageId);
    if (_viewer.stylePreviewStatus == 'loading-local') {
      return const InspectorChip('Готовим текст', tone: 'warn');
    }
    if (_viewer.stylePreviewStatus == 'local-error') {
      return const InspectorChip('Ошибка предпросмотра', tone: 'bad');
    }
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
}
