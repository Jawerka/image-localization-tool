import 'package:flutter/material.dart';

import '../../state/viewer_state.dart';
import '../theme.dart';

/// Плавающая пилюля «N правок · не применены» с кнопкой «Готово».
class DonePill extends StatelessWidget {
  const DonePill({super.key, required this.viewer});

  final ViewerState viewer;

  static String editsLabel(int count) {
    final mod10 = count % 10;
    final mod100 = count % 100;
    final word = mod10 == 1 && mod100 != 11
        ? 'правка'
        : (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
            ? 'правки'
            : 'правок');
    return '$count $word';
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return MouseRegion(
      cursor: SystemMouseCursors.move,
      child: GestureDetector(
        onPanUpdate: (details) {
          var delta = details.delta;
          // не даём утащить пилюлю за пределы разумного
          final offset = viewer.pillOffset;
          if (offset.dx.abs() > 400) delta = Offset(0, delta.dy);
          if (offset.dy.abs() > 300) delta = Offset(delta.dx, 0);
          viewer.dragPill(delta);
        },
        child: Container(
          key: const Key('viewer-done-pill'),
          padding: const EdgeInsets.only(left: 4, right: 4),
          decoration: BoxDecoration(
            color: palette.surface2.withValues(alpha: 0.96),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: palette.border),
            boxShadow: const [
              BoxShadow(
                color: Color(0x55000000),
                blurRadius: 14,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Icon(
                  Icons.drag_indicator,
                  size: 16,
                  color: palette.textMuted,
                ),
              ),
              Text(
                '${editsLabel(viewer.editCount)} · не применены',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: palette.textPrimary),
              ),
              const SizedBox(width: 6),
              TextButton(
                key: const Key('viewer-done-apply'),
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  minimumSize: const Size(0, 26),
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: viewer.commitDeferredEdits,
                child: const Text('Готово'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
