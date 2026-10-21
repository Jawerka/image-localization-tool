import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'inspector_controls.dart';

/// Вкладка «Трансформация»: позиция текста, поворот, рамка, искривление и
/// сброс геометрии. Область вёрстки и позиция текста не смешиваются.
class RegionTransformSection extends StatefulWidget {
  const RegionTransformSection({
    super.key,
    required this.viewer,
    required this.region,
  });

  final ViewerState viewer;
  final Region region;

  @override
  State<RegionTransformSection> createState() => _RegionTransformSectionState();
}

class _RegionTransformSectionState extends State<RegionTransformSection> {
  final _rotation = TextEditingController();
  final _rotationFocus = FocusNode();
  final _positionX = TextEditingController();
  final _positionY = TextEditingController();
  final _positionXFocus = FocusNode();
  final _positionYFocus = FocusNode();

  static const _warps = [
    ('none', 'Нет'),
    ('arc-up', 'Дуга вверх'),
    ('arc-down', 'Дуга вниз'),
    ('ring', 'Кольцо'),
    ('wave', 'Волна'),
    ('flag', 'Флаг'),
    ('perspective', 'Перспектива'),
    ('mesh', 'Сетка'),
  ];

  String get _id => widget.region.id;

  Map<String, dynamic> get _style {
    final raw = widget.region.data['style'];
    return raw is Map ? raw.cast<String, dynamic>() : const {};
  }

  @override
  void initState() {
    super.initState();
    _rotationFocus.addListener(() {
      if (!_rotationFocus.hasFocus) _commitRotation();
    });
    _positionXFocus.addListener(() {
      if (!_positionXFocus.hasFocus) _commitPosition();
    });
    _positionYFocus.addListener(() {
      if (!_positionYFocus.hasFocus) _commitPosition();
    });
  }

  @override
  void dispose() {
    _rotation.dispose();
    _rotationFocus.dispose();
    _positionX.dispose();
    _positionY.dispose();
    _positionXFocus.dispose();
    _positionYFocus.dispose();
    super.dispose();
  }

  void _sync(TextEditingController controller, String value, FocusNode node) {
    if (node.hasFocus) return;
    if (controller.text != value) controller.text = value;
  }

  @override
  Widget build(BuildContext context) {
    final viewer = widget.viewer;
    final region = widget.region;
    final style = _style;
    final rotation = region.rotation;
    final position = viewer.textAnchorFor(region);
    final warp = style['warp'] is Map
        ? (style['warp'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final bendRaw = warp['bend'];
    final bend = bendRaw is num ? bendRaw.toDouble() : 0.0;
    final choice = _warpChoice('${warp['kind'] ?? 'none'}', bend);
    final skew = style['skew_x'];
    final hasSkew = skew is num && skew.abs() > 1e-6;

    _sync(
      _rotation,
      rotation == rotation.roundToDouble()
          ? '${rotation.round()}'
          : rotation.toStringAsFixed(1),
      _rotationFocus,
    );
    _sync(_positionX, '${position.dx.round()}', _positionXFocus);
    _sync(_positionY, '${position.dy.round()}', _positionYFocus);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (hasSkew)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(
              'Наклон (skew) не поддержан локально: показан серверный предпросмотр.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        InspectorAction(
          key: Key('region-text-move-$_id'),
          label: 'Двигать текст',
          icon: Icons.open_with,
          active: viewer.isTextMoveActive(_id),
          onPressed: () => viewer.toggleTextMove(_id),
        ),
        SizedBox(
          width: 96,
          child: InspectorField(
            label: 'Поворот, °',
            child: InspectorInput(
              key: const Key('style-rotation'),
              controller: _rotation,
              focusNode: _rotationFocus,
              numeric: true,
              onSubmitted: (_) => _commitRotation(),
            ),
          ),
        ),
        InspectorField(
          label: 'Позиция текста',
          child: Row(
            children: [
              Expanded(
                child: InspectorInput(
                  key: const Key('style-text-position-x'),
                  controller: _positionX,
                  focusNode: _positionXFocus,
                  numeric: true,
                  onSubmitted: (_) => _commitPosition(),
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: InspectorInput(
                  key: const Key('style-text-position-y'),
                  controller: _positionY,
                  focusNode: _positionYFocus,
                  numeric: true,
                  onSubmitted: (_) => _commitPosition(),
                ),
              ),
              IconButton(
                key: const Key('style-text-position-reset'),
                tooltip: 'Сбросить позицию текста',
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: () => viewer.resetTextPosition(_id),
                icon: const Icon(Icons.restart_alt),
              ),
            ],
          ),
        ),
        const SizedBox(height: 4),
        _nudgePad(),
        InspectorLabel('Искривление'),
        Wrap(
          spacing: 4,
          runSpacing: 4,
          children: [
            for (final (value, label) in _warps)
              InspectorAction(
                key: Key('style-warp-$value'),
                label: label,
                active: choice == value,
                onPressed: () => viewer.setRegionWarpPreset(_id, value),
              ),
          ],
        ),
        Row(
          children: [
            Expanded(
              child: Slider(
                key: const Key('style-warp-bend'),
                value: bend.clamp(-1, 1),
                min: -1,
                max: 1,
                onChanged: (value) => viewer.setRegionWarpBend(_id, value),
              ),
            ),
            SizedBox(
              width: 40,
              child: Text(
                bend.toStringAsFixed(2),
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
          ],
        ),
        Wrap(
          spacing: 4,
          runSpacing: 4,
          children: [
            InspectorAction(
              key: const Key('style-reset'),
              label: 'Сбросить поворот и искривление',
              icon: Icons.refresh,
              onPressed: () => viewer.resetRegionStyle(_id),
            ),
          ],
        ),
      ],
    );
  }

  Widget _nudgePad() {
    final theme = Theme.of(context);
    final palette = IltPalette.of(context);
    Widget cell(String direction, IconData icon, String tooltip) {
      return Tooltip(
        message: '$tooltip (Shift: 10px)',
        child: InkWell(
          key: Key('region-nudge-$direction-$_id'),
          onTap: () => widget.viewer.nudgeSelectedRegion(
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
        Text('Рамка ', style: theme.textTheme.labelSmall),
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

  String _warpChoice(String kind, double bend) {
    if (kind == 'arc') return bend >= 0 ? 'arc-up' : 'arc-down';
    if (kind == 'wave' ||
        kind == 'flag' ||
        kind == 'ring' ||
        kind == 'perspective' ||
        kind == 'mesh' ||
        kind == 'none') {
      return kind;
    }
    return 'none';
  }

  void _commitRotation() {
    final value = num.tryParse(_rotation.text.replaceAll(',', '.'));
    widget.viewer.setRegionRotation(_id, (value ?? 0).toDouble());
  }

  void _commitPosition() {
    final x = num.tryParse(_positionX.text.replaceAll(',', '.'));
    final y = num.tryParse(_positionY.text.replaceAll(',', '.'));
    if (x == null || y == null) {
      final current = widget.viewer.textAnchorFor(widget.region);
      _positionX.text = '${current.dx.round()}';
      _positionY.text = '${current.dy.round()}';
      return;
    }
    final size = widget.viewer.imageSize;
    final dx = size.width > 0
        ? x.toDouble().clamp(0, size.width).toDouble()
        : x.toDouble();
    final dy = size.height > 0
        ? y.toDouble().clamp(0, size.height).toDouble()
        : y.toDouble();
    widget.viewer.setTextPosition(_id, Offset(dx, dy));
  }
}
