import 'package:flutter/material.dart';

import 'theme.dart';

/// Постоянные подписанные действия скрытия и возврата боковых панелей.
class WorkspacePanels extends StatefulWidget {
  const WorkspacePanels({
    super.key,
    required this.pages,
    required this.viewer,
    required this.inspector,
  });

  final Widget pages;
  final Widget viewer;
  final Widget inspector;

  @override
  State<WorkspacePanels> createState() => _WorkspacePanelsState();
}

class _WorkspacePanelsState extends State<WorkspacePanels> {
  bool _pagesVisible = true;
  bool _inspectorVisible = true;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Column(
      children: [
        Container(
          key: const Key('workspace-panel-controls'),
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: palette.surface1,
            border: Border(bottom: BorderSide(color: palette.line)),
          ),
          child: Wrap(
            spacing: 6,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text('Панели', style: Theme.of(context).textTheme.labelSmall),
              _toggle(
                key: const Key('workspace-toggle-pages'),
                visible: _pagesVisible,
                name: 'страницы',
                tooltip: 'Левая панель: страницы и очередь',
                icon: Icons.view_list_outlined,
                onPressed: () => setState(() => _pagesVisible = !_pagesVisible),
              ),
              _toggle(
                key: const Key('workspace-toggle-inspector'),
                visible: _inspectorVisible,
                name: 'инспектор',
                tooltip: 'Правая панель: текст и свойства страницы',
                icon: Icons.view_sidebar_outlined,
                onPressed: () =>
                    setState(() => _inspectorVisible = !_inspectorVisible),
              ),
            ],
          ),
        ),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _panel(visible: _pagesVisible, child: widget.pages),
              Expanded(child: widget.viewer),
              _panel(visible: _inspectorVisible, child: widget.inspector),
            ],
          ),
        ),
      ],
    );
  }

  Widget _toggle({
    required Key key,
    required bool visible,
    required String name,
    required String tooltip,
    required IconData icon,
    required VoidCallback onPressed,
  }) => Semantics(
    toggled: visible,
    child: Tooltip(
      message: tooltip,
      child: OutlinedButton.icon(
        key: key,
        onPressed: onPressed,
        icon: Icon(icon, size: 16),
        label: Text('${visible ? 'Скрыть' : 'Показать'} $name'),
      ),
    ),
  );

  // Скрытие не уничтожает вкладки, прокрутку и несохранённый ввод панели.
  Widget _panel({required bool visible, required Widget child}) => ExcludeFocus(
    excluding: !visible,
    child: Visibility(visible: visible, maintainState: true, child: child),
  );
}
