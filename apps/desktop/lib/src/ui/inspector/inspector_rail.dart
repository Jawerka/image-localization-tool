import 'package:flutter/material.dart';

import '../../state/viewer_state.dart';
import '../../state/workspace_state.dart';
import '../theme.dart';
import 'page_facts.dart';
import 'region_card.dart';
import 'run_report.dart';

/// Правая панель: карточки регионов, страница и отчёт прогона (024).
class InspectorRail extends StatefulWidget {
  const InspectorRail({
    super.key,
    required this.workspace,
    required this.metrics,
    this.onOpenLog,
  });

  final WorkspaceState workspace;
  final ChromeMetrics metrics;
  final VoidCallback? onOpenLog;

  @override
  State<InspectorRail> createState() => _InspectorRailState();
}

class _InspectorRailState extends State<InspectorRail> {
  String _tab = 'text';
  bool _tabTouched = false;
  bool _lastBusy = false;
  String? _lastSelected;
  final ScrollController _scroll = ScrollController();
  final Map<String, GlobalKey> _cardKeys = {};
  final Map<String, RegionTab> _regionTabs = {};

  WorkspaceState get _workspace => widget.workspace;
  ViewerState get _viewer => _workspace.viewer;

  bool get _reportVisible => _workspace.busy || _workspace.mode == 'run';

  String get _effectiveTab {
    if (_tab == 'report' && !_reportVisible) return 'text';
    return _tab;
  }

  @override
  void initState() {
    super.initState();
    _workspace.addListener(_onWorkspace);
    _viewer.ensureFonts();
  }

  @override
  void dispose() {
    _workspace.removeListener(_onWorkspace);
    _scroll.dispose();
    super.dispose();
  }

  void _onWorkspace() {
    if (!mounted) return;
    final busy = _workspace.busy;
    if (busy && !_lastBusy && !_tabTouched && _reportVisible) {
      _tab = 'report';
    }
    _lastBusy = busy;
    final selected = _viewer.selectedRegionId;
    if (selected != _lastSelected) {
      _lastSelected = selected;
      if (selected != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) => _ensureVisible(selected));
      }
    }
    _viewer.ensureFonts();
    setState(() {});
  }

  String _regionTabKey(String regionId) =>
      '${_workspace.project?.id ?? ''}/${_viewer.pageId ?? ''}/$regionId';

  RegionTab _regionTab(String regionId) =>
      _regionTabs[_regionTabKey(regionId)] ?? RegionTab.text;

  void _ensureVisible(String regionId) {
    final context = _cardKeys[regionId]?.currentContext;
    if (context == null) return;
    Scrollable.ensureVisible(
      context,
      duration: const Duration(milliseconds: 180),
      alignment: 0.1,
    );
  }

  void _stepRegion(int delta) {
    final regions = _viewer.document?.regions ?? const [];
    if (regions.isEmpty) return;
    final index = regions.indexWhere((region) => region.id == _viewer.selectedRegionId);
    final next = index < 0
        ? (delta > 0 ? 0 : regions.length - 1)
        : (index + delta + regions.length) % regions.length;
    _viewer.selectRegion(regions[next].id);
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final regions = _viewer.document?.regions ?? const [];
    final selectedIndex =
        regions.indexWhere((region) => region.id == _viewer.selectedRegionId);
    final tab = _effectiveTab;
    return Container(
      key: const Key('shell-inspector-rail'),
      width: widget.metrics.inspectorWidth,
      decoration: BoxDecoration(
        color: palette.surface1,
        border: Border(left: BorderSide(color: palette.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 6, 6, 4),
            child: Row(
              children: [
                Icon(Icons.tune, size: 16, color: palette.textMuted),
                const SizedBox(width: 6),
                Text(
                  'Инспектор',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
                const Spacer(),
                if (regions.isNotEmpty) ...[
                  IconButton(
                    key: const Key('inspector-region-prev'),
                    tooltip: 'Предыдущий регион',
                    visualDensity: VisualDensity.compact,
                    iconSize: 16,
                    onPressed: () => _stepRegion(-1),
                    icon: const Icon(Icons.keyboard_arrow_up),
                  ),
                  Text(
                    '${selectedIndex < 0 ? 0 : selectedIndex + 1} / ${regions.length}',
                    key: const Key('inspector-region-counter'),
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                  IconButton(
                    key: const Key('inspector-region-next'),
                    tooltip: 'Следующий регион',
                    visualDensity: VisualDensity.compact,
                    iconSize: 16,
                    onPressed: () => _stepRegion(1),
                    icon: const Icon(Icons.keyboard_arrow_down),
                  ),
                ],
              ],
            ),
          ),
          _tabs(context, tab),
          const Divider(height: 1),
          Expanded(child: _body(context, tab)),
        ],
      ),
    );
  }

  Widget _tabs(BuildContext context, String tab) {
    final palette = IltPalette.of(context);
    Widget item(String value, String label, {Key? key}) {
      final active = tab == value;
      return Expanded(
        child: InkWell(
          key: key,
          onTap: () => setState(() {
            _tab = value;
            _tabTouched = true;
          }),
          child: Container(
            alignment: Alignment.center,
            padding: const EdgeInsets.symmetric(vertical: 5),
            decoration: BoxDecoration(
              color: active ? palette.surface2 : Colors.transparent,
              borderRadius: BorderRadius.circular(5),
            ),
            child: Text(
              label,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: active ? palette.textPrimary : palette.textMuted,
                  ),
            ),
          ),
        ),
      );
    }

    return Container(
      margin: const EdgeInsets.fromLTRB(10, 0, 10, 6),
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: palette.bgSecondary,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: palette.line),
      ),
      child: Row(
        children: [
          item('text', 'Текст', key: const Key('inspector-tab-text')),
          item('page', 'Страница', key: const Key('inspector-tab-page')),
          if (_reportVisible)
            item('report', 'Отчёт', key: const Key('inspector-tab-report')),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, String tab) {
    if (tab == 'report') {
      return RunReport(workspace: _workspace, onOpenLog: widget.onOpenLog);
    }
    if (tab == 'page') {
      return PageFacts(workspace: _workspace);
    }
    return _textTab(context);
  }

  Widget _textTab(BuildContext context) {
    final awaiting = _awaitingText();
    if (awaiting != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Text(
            awaiting,
            key: const Key('inspector-awaiting'),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      );
    }
    final regions = _viewer.document?.regions ?? const [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 0, 10, 6),
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('inspector-add-region'),
                  onPressed: _viewer.addRegionAtViewCenter,
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(0, 48),
                  ),
                  icon: const Icon(Icons.add, size: 14),
                  label: const Text('Добавить регион'),
                ),
              ),
              const SizedBox(width: 4),
              IconButton(
                key: const Key('inspector-focus-problem'),
                tooltip: 'Следующая проблема (N)',
                visualDensity: VisualDensity.compact,
                onPressed: _workspace.focusNextProblem,
                icon: const Icon(Icons.adjust, size: 16),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(10, 0, 10, 12),
            itemCount: regions.length,
            itemBuilder: (context, index) {
              final region = regions[index];
              final key = _cardKeys.putIfAbsent(region.id, GlobalKey.new);
              return KeyedSubtree(
                key: key,
                child: RegionCard(
                  viewer: _viewer,
                  region: region,
                  index: index,
                  selected: region.id == _viewer.selectedRegionId,
                  tab: _regionTab(region.id),
                  onTabSelected: (tab) => setState(
                    () => _regionTabs[_regionTabKey(region.id)] = tab,
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  String? _awaitingText() {
    final page = _workspace.activePage;
    if (!_workspace.hasProject) {
      return 'Откройте главу — здесь появятся регионы и их переводы.';
    }
    if (page == null) {
      return 'Выберите страницу, чтобы увидеть её регионы и переводы.';
    }
    if (page.isRunning || page.isQueued) {
      return 'Страница ещё в работе. Регионы появятся после распознавания.';
    }
    if (_viewer.loading || _viewer.document == null) {
      return 'Страница открывается.';
    }
    if ((_viewer.document?.regions ?? const []).isEmpty) {
      return 'Нет регионов. Добавьте рамку или запустите перевод.';
    }
    return null;
  }
}
