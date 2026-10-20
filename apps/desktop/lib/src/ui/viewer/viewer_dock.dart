import 'dart:async';

import 'package:flutter/material.dart';

import '../../state/viewer_state.dart';
import '../../state/workspace_state.dart';
import '../theme.dart';

/// Хост плавающего дока: сторона (сверху/снизу) и перетаскивание за ручку.
///
/// Док следует за указателем; отпускание дальше ⅓ высоты сцены переносит его
/// к верхнему (12 px) или нижнему (16 px) краю и сохраняет позицию настройкой
/// `dock_position`. Позиция читается из workspace, PUT шлёт сам workspace.
class ViewerDockHost extends StatefulWidget {
  const ViewerDockHost({super.key, required this.workspace});

  final WorkspaceState workspace;

  @override
  State<ViewerDockHost> createState() => _ViewerDockHostState();
}

class _ViewerDockHostState extends State<ViewerDockHost> {
  static const double _topInset = 12;
  static const double _bottomInset = 16;

  double _dragDy = 0;
  bool _dragging = false;

  WorkspaceState get _workspace => widget.workspace;

  void _onDragStart(DragStartDetails details) {
    setState(() {
      _dragging = true;
      _dragDy = 0;
    });
  }

  void _onDragUpdate(DragUpdateDetails details) {
    setState(() => _dragDy += details.delta.dy);
  }

  void _onDragEnd(DragEndDetails details, double height) {
    final nextTop = _dragDy.abs() > height / 3
        ? _dragDy < 0
        : _workspace.dockAtTop;
    setState(() {
      _dragging = false;
      _dragDy = 0;
    });
    if (nextTop != _workspace.dockAtTop) {
      unawaited(_workspace.setDockPosition(nextTop));
    }
  }

  void _onDragCancel() {
    setState(() {
      _dragging = false;
      _dragDy = 0;
    });
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final atTop = _workspace.dockAtTop;
        return Stack(
          children: [
            Positioned(
              left: 0,
              right: 0,
              top: atTop ? _topInset + _dragDy : null,
              bottom: atTop ? null : _bottomInset - _dragDy,
              child: Center(
                child: ViewerDock(
                  viewer: _workspace.viewer,
                  grip: _grip(palette, constraints.maxHeight),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _grip(IltPalette palette, double height) {
    return MouseRegion(
      cursor: _dragging
          ? SystemMouseCursors.grabbing
          : SystemMouseCursors.grab,
      child: GestureDetector(
        key: const Key('viewer-dock-grip'),
        behavior: HitTestBehavior.opaque,
        onVerticalDragStart: _onDragStart,
        onVerticalDragUpdate: _onDragUpdate,
        onVerticalDragEnd: (details) => _onDragEnd(details, height),
        onVerticalDragCancel: _onDragCancel,
        child: Padding(
          padding: const EdgeInsets.only(right: 4),
          child: Icon(Icons.drag_indicator, size: 16, color: palette.textMuted),
        ),
      ),
    );
  }
}

/// Плавающий док канваса: вид, слои, инструменты, кисть, undo/redo, зум.
class ViewerDock extends StatelessWidget {
  const ViewerDock({super.key, required this.viewer, this.grip});

  final ViewerState viewer;

  /// Ручка перетаскивания (собирается [ViewerDockHost]).
  final Widget? grip;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return AnimatedBuilder(
      animation: Listenable.merge([viewer, viewer.session]),
      builder: (context, _) {
        return Container(
          key: const Key('viewer-dock'),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: palette.surface2.withValues(alpha: 0.96),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: palette.border),
            boxShadow: const [
              BoxShadow(
                color: Color(0x55000000),
                blurRadius: 16,
                offset: Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              ?grip,
              _viewSegment(palette),
              _separator(palette),
              _layerToggle(
                palette,
                icon: Icons.layers_outlined,
                tooltip: 'Слой рамок (L)',
                active: viewer.showBoxes,
                onTap: viewer.toggleBoxes,
                keyName: 'dock-boxes',
              ),
              _layerToggle(
                palette,
                icon: Icons.opacity_outlined,
                tooltip:
                    'Маска (M): чёрный — вне маски, зелёный — добавлено, красный — исключено',
                active: viewer.showMask,
                onTap: viewer.toggleMask,
                keyName: 'dock-mask',
              ),
              _separator(palette),
              _toolSegment(palette),
              _separator(palette),
              _brushSize(palette, context),
              _separator(palette),
              _iconButton(
                palette,
                icon: Icons.undo,
                tooltip: 'Отменить (Ctrl+Z)',
                onTap: viewer.canUndo ? viewer.undo : null,
                keyName: 'dock-undo',
              ),
              _iconButton(
                palette,
                icon: Icons.redo,
                tooltip: 'Повторить (Ctrl+Y)',
                onTap: viewer.canRedo ? viewer.redo : null,
                keyName: 'dock-redo',
              ),
              _separator(palette),
              _zoom(palette, context),
            ],
          ),
        );
      },
    );
  }

  Widget _viewSegment(IltPalette palette) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _iconButton(
          palette,
          icon: Icons.image_outlined,
          tooltip: 'Оригинал (1)',
          active: viewer.view == 'original',
          onTap: () => viewer.setView('original'),
          keyName: 'dock-view-original',
        ),
        _iconButton(
          palette,
          icon: Icons.translate,
          tooltip: 'Результат (2)',
          active: viewer.view == 'result',
          onTap: () => viewer.setView('result'),
          keyName: 'dock-view-result',
        ),
        _iconButton(
          palette,
          icon: Icons.compare_outlined,
          tooltip: 'Сравнение (3)',
          active: viewer.view == 'compare',
          onTap: () => viewer.setView('compare'),
          keyName: 'dock-view-compare',
        ),
      ],
    );
  }

  Widget _toolSegment(IltPalette palette) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _iconButton(
          palette,
          icon: Icons.near_me_outlined,
          tooltip: 'Выбор (V)',
          active: viewer.tool == 'select',
          onTap: () => viewer.setTool('select'),
          keyName: 'dock-tool-select',
        ),
        _iconButton(
          palette,
          icon: Icons.crop_free,
          tooltip: 'Регион (R)',
          active: viewer.tool == 'region',
          onTap: () => viewer.setTool('region'),
          keyName: 'dock-tool-region',
        ),
        _iconButton(
          palette,
          icon: Icons.brush_outlined,
          tooltip: 'Кисть: ЛКМ — рисовать, ПКМ — ластик (B)',
          active: viewer.tool == 'brush',
          onTap: () => viewer.setTool('brush'),
          keyName: 'dock-tool-brush',
        ),
        _iconButton(
          palette,
          icon: Icons.gesture,
          tooltip: 'Лассо (P)',
          active: viewer.tool == 'polyline',
          onTap: () => viewer.setTool('polyline'),
          keyName: 'dock-tool-lasso',
        ),
        _iconButton(
          palette,
          icon: Icons.pan_tool_outlined,
          tooltip: 'Рука (H)',
          active: viewer.tool == 'hand',
          onTap: () => viewer.setTool('hand'),
          keyName: 'dock-tool-hand',
        ),
      ],
    );
  }

  Widget _brushSize(IltPalette palette, BuildContext context) {
    final theme = Theme.of(context);
    return MenuAnchor(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(palette.surface2),
      ),
      menuChildren: [
        SizedBox(
          width: 230,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Text('Толщина кисти', style: theme.textTheme.labelSmall),
                    const Spacer(),
                    Text(
                      '${viewer.brushSize.round()} px',
                      style: theme.textTheme.labelSmall,
                    ),
                  ],
                ),
                Slider(
                  key: const Key('dock-brush-slider'),
                  min: 1,
                  max: 64,
                  divisions: 63,
                  value: viewer.brushSize.clamp(1, 64),
                  onChanged: viewer.setBrushSize,
                ),
                Text(
                  'ЛКМ — рисовать, ПКМ — стирать. Клавиши [ и ] меняют шаг.',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: palette.textMuted),
                ),
              ],
            ),
          ),
        ),
      ],
      builder: (context, controller, child) => _iconButton(
        palette,
        icon: Icons.brush,
        tooltip: 'Толщина кисти ( [ / ] )',
        active: viewer.tool == 'brush',
        onTap: () =>
            controller.isOpen ? controller.close() : controller.open(),
        keyName: 'dock-brush-size',
        label: '${viewer.brushSize.round()}',
      ),
    );
  }

  Widget _zoom(IltPalette palette, BuildContext context) {
    final theme = Theme.of(context);
    final session = viewer.session;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _iconButton(
          palette,
          icon: Icons.remove,
          tooltip: 'Уменьшить',
          onTap: () => session.zoomStep(-1),
          keyName: 'dock-zoom-out',
        ),
        TextButton(
          key: const Key('dock-zoom-value'),
          style: TextButton.styleFrom(
            minimumSize: const Size(0, 30),
            padding: const EdgeInsets.symmetric(horizontal: 8),
          ),
          onPressed: session.fit,
          child: Text(
            session.zoomLabel,
            style: theme.textTheme.labelSmall,
          ),
        ),
        _iconButton(
          palette,
          icon: Icons.swap_horiz,
          tooltip: 'По ширине',
          active: session.zoomMode == 'fit-width',
          onTap: session.fitWidth,
          keyName: 'dock-zoom-fit-width',
        ),
        _iconButton(
          palette,
          icon: Icons.add,
          tooltip: 'Увеличить',
          onTap: () => session.zoomStep(1),
          keyName: 'dock-zoom-in',
        ),
      ],
    );
  }

  Widget _layerToggle(
    IltPalette palette, {
    required IconData icon,
    required String tooltip,
    required bool active,
    required VoidCallback onTap,
    required String keyName,
  }) =>
      _iconButton(
        palette,
        icon: icon,
        tooltip: tooltip,
        active: active,
        onTap: onTap,
        keyName: keyName,
      );

  Widget _separator(IltPalette palette) => Container(
        width: 1,
        height: 22,
        margin: const EdgeInsets.symmetric(horizontal: 6),
        color: palette.line,
      );

  Widget _iconButton(
    IltPalette palette, {
    required IconData icon,
    required String tooltip,
    required VoidCallback? onTap,
    required String keyName,
    bool active = false,
    String? label,
  }) {
    final color = onTap == null
        ? palette.textMuted.withValues(alpha: 0.4)
        : active
            ? palette.primary
            : palette.textPrimary;
    return Tooltip(
      message: tooltip,
      waitDuration: const Duration(milliseconds: 500),
      child: InkWell(
        key: Key(keyName),
        borderRadius: BorderRadius.circular(6),
        onTap: onTap,
        child: Container(
          width: label == null ? 30 : 46,
          height: 30,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: active ? palette.primary.withValues(alpha: 0.14) : null,
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 17, color: color),
              if (label != null)
                Padding(
                  padding: const EdgeInsets.only(left: 2),
                  child: Text(
                    label,
                    style: TextStyle(fontSize: 11, color: color),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
