import 'package:flutter/material.dart';

import '../theme.dart';

/// Мелкие общие элементы инспектора (024).

/// Подпись поля/секции.
class InspectorLabel extends StatelessWidget {
  const InspectorLabel(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Row(
        children: [
          Expanded(child: Text(text, style: theme.textTheme.labelSmall)),
          ?trailing,
        ],
      ),
    );
  }
}

/// Компактная кнопка-действие карточки.
class InspectorAction extends StatelessWidget {
  const InspectorAction({
    super.key,
    required this.label,
    this.icon,
    this.onPressed,
    this.active = false,
    this.danger = false,
    this.busy = false,
  });

  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final bool active;
  final bool danger;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final color = danger
        ? palette.textError
        : active
            ? palette.primaryHover
            : palette.textPrimary;
    return OutlinedButton.icon(
      onPressed: onPressed,
      style: OutlinedButton.styleFrom(
        visualDensity: VisualDensity.compact,
        minimumSize: const Size(0, 26),
        padding: const EdgeInsets.symmetric(horizontal: 8),
        foregroundColor: color,
        side: BorderSide(
          color: active ? palette.primaryHover : palette.border,
        ),
        textStyle: theme.textTheme.labelSmall?.copyWith(color: color),
      ),
      icon: busy
          ? const SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(icon ?? Icons.circle, size: 13, color: color),
      label: Text(label),
    );
  }
}

/// Маленький чип состояния.
class InspectorChip extends StatelessWidget {
  const InspectorChip(this.text, {super.key, this.tone = 'ghost'});

  final String text;
  final String tone;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final (bg, fg) = switch (tone) {
      'ok' => (palette.textSuccess.withValues(alpha: 0.16), palette.textSuccess),
      'warn' => (palette.textWarning.withValues(alpha: 0.16), palette.textWarning),
      'bad' => (palette.textError.withValues(alpha: 0.16), palette.textError),
      _ => (palette.surface3, palette.textMuted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(color: fg),
      ),
    );
  }
}

/// Сворачиваемая секция карточки (аналог `details.sect`).
class Disclosure extends StatefulWidget {
  const Disclosure({
    super.key,
    required this.title,
    required this.child,
    this.initiallyExpanded = false,
  });

  final String title;
  final Widget child;
  final bool initiallyExpanded;

  @override
  State<Disclosure> createState() => _DisclosureState();
}

class _DisclosureState extends State<Disclosure> {
  late bool _open = widget.initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          key: Key('disclosure-${widget.title}'),
          onTap: () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              children: [
                Icon(
                  _open ? Icons.expand_more : Icons.chevron_right,
                  size: 15,
                  color: palette.textMuted,
                ),
                const SizedBox(width: 4),
                Text(
                  widget.title,
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
        ),
        if (_open) widget.child,
      ],
    );
  }
}

/// Поле с подписью сверху (колонка во всю ширину рельса).
class InspectorField extends StatelessWidget {
  const InspectorField({
    super.key,
    required this.label,
    required this.child,
    this.trailing,
  });

  final String label;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InspectorLabel(label, trailing: trailing),
          child,
        ],
      ),
    );
  }
}

/// Компактное текстовое поле рельса.
class InspectorInput extends StatelessWidget {
  const InspectorInput({
    super.key,
    required this.controller,
    this.focusNode,
    this.onChanged,
    this.onSubmitted,
    this.hint,
    this.maxLines = 1,
    this.minLines = 1,
    this.numeric = false,
    this.readOnly = false,
  });

  final TextEditingController controller;
  final FocusNode? focusNode;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final String? hint;
  final int maxLines;
  final int minLines;
  final bool numeric;
  final bool readOnly;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final singleLine = minLines == 1 && maxLines == 1;
    final field = TextField(
      controller: controller,
      focusNode: focusNode,
      onChanged: onChanged,
      onSubmitted: onSubmitted,
      readOnly: readOnly,
      minLines: minLines,
      maxLines: maxLines,
      textAlignVertical:
          singleLine ? TextAlignVertical.center : null,
      keyboardType: numeric
          ? const TextInputType.numberWithOptions(signed: true, decimal: true)
          : TextInputType.multiline,
      style: Theme.of(context).textTheme.bodySmall,
      decoration: InputDecoration(
        isDense: true,
        hintText: hint,
        hintStyle: Theme.of(context).textTheme.labelSmall,
        contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
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
    );
    // Однострочные поля инспектора — общей высоты 32; «Перевод»/«Оригинал»
    // (minLines > 1) остаются многострочными.
    if (!singleLine) return field;
    return SizedBox(height: kFieldHeight, child: field);
  }
}

/// «#rrggbb» → [r, g, b]; невалидное даёт null.
List<int>? hexToRgb(String value) {
  final text = value.trim().replaceFirst('#', '');
  if (text.length != 6) return null;
  final value0 = int.tryParse(text, radix: 16);
  if (value0 == null) return null;
  return [(value0 >> 16) & 0xFF, (value0 >> 8) & 0xFF, value0 & 0xFF];
}

/// [r, g, b] → «#rrggbb».
String rgbToHex(Object? raw) {
  final rgb = raw is List ? raw : const [0, 0, 0];
  String channel(Object? value) {
    final number = value is num ? value : num.tryParse('$value') ?? 0;
    return number.round().clamp(0, 255).toInt().toRadixString(16).padLeft(2, '0');
  }

  final list = rgb;
  return '#${channel(list.isNotEmpty ? list[0] : 0)}'
      '${channel(list.length > 1 ? list[1] : 0)}'
      '${channel(list.length > 2 ? list[2] : 0)}';
}
