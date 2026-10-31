import 'package:flutter/material.dart';

import 'theme.dart';

/// Заголовок секции с пояснением.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.lead});

  final String title;
  final String? lead;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: theme.textTheme.titleSmall),
        if (lead != null) ...[
          const SizedBox(height: 4),
          Text(lead!, style: theme.textTheme.bodySmall),
        ],
        const SizedBox(height: 10),
        Divider(color: palette.line, height: 1),
        const SizedBox(height: 10),
      ],
    );
  }
}

/// Строка «подпись — контрол».
class FieldRow extends StatelessWidget {
  const FieldRow({
    super.key,
    required this.label,
    required this.child,
    this.hint,
    this.width = 240,
  });

  final String label;
  final Widget child;
  final String? hint;
  final double width;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: theme.textTheme.bodySmall),
                if (hint != null)
                  Text(hint!, style: theme.textTheme.labelSmall),
              ],
            ),
          ),
          const SizedBox(width: 16),
          SizedBox(width: width, child: child),
        ],
      ),
    );
  }
}

/// Компактный выпадающий список.
class IltSelect extends StatelessWidget {
  const IltSelect({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  final String value;
  final List<(String, String)> options;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return SizedBox(
      height: kFieldHeight,
      child: DropdownButtonFormField<String>(
        initialValue: options.any((item) => item.$1 == value) ? value : null,
        isDense: true,
        isExpanded: true,
        decoration: InputDecoration(
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8),
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
        style: Theme.of(context).textTheme.bodySmall,
        dropdownColor: palette.surface2,
        items: [
          for (final (key, label) in options)
            DropdownMenuItem(value: key, child: Text(label)),
        ],
        onChanged:
            onChanged == null ? null : (value) => onChanged!(value ?? ''),
      ),
    );
  }
}

/// Текстовое поле ввода настройки.
///
/// Контроллер вместо ``initialValue`` с ключом-значением: программное
/// обновление подхватывается, а фокус при наборе не теряется.
class IltTextField extends StatefulWidget {
  const IltTextField({
    super.key,
    required this.value,
    this.onChanged,
    this.hint,
    this.obscure = false,
    this.enabled = true,
  });

  final String value;
  final ValueChanged<String>? onChanged;
  final String? hint;
  final bool obscure;
  final bool enabled;

  @override
  State<IltTextField> createState() => _IltTextFieldState();
}

class _IltTextFieldState extends State<IltTextField> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.value);

  @override
  void didUpdateWidget(covariant IltTextField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != oldWidget.value && widget.value != _controller.text) {
      _controller.text = widget.value;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return SizedBox(
      height: kFieldHeight,
      child: TextFormField(
        controller: _controller,
        style: Theme.of(context).textTheme.bodySmall,
        obscureText: widget.obscure,
        enabled: widget.enabled,
        textAlignVertical: TextAlignVertical.center,
        decoration: InputDecoration(
          isDense: true,
          hintText: widget.hint,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8),
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
        onChanged: widget.onChanged,
      ),
    );
  }
}

/// Числовое поле.
class IltNumberField extends StatelessWidget {
  const IltNumberField({
    super.key,
    required this.value,
    this.onChanged,
    this.min,
    this.max,
    this.step = 1,
    this.decimals = false,
  });

  final num value;
  final ValueChanged<num>? onChanged;
  final num? min;
  final num? max;
  final num step;
  final bool decimals;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return SizedBox(
      height: kFieldHeight,
      child: TextFormField(
        initialValue: decimals ? '$value' : '${value.round()}',
        key: ValueKey('num-$value'),
        style: Theme.of(context).textTheme.bodySmall,
        textAlignVertical: TextAlignVertical.center,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8),
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
        onChanged: onChanged == null
            ? null
            : (text) {
                final parsed = decimals
                    ? double.tryParse(text.replaceAll(',', '.'))
                    : int.tryParse(text.trim());
                if (parsed == null) return;
                var result = parsed;
                if (min != null && result < min!) result = min!;
                if (max != null && result > max!) result = max!;
                onChanged!(result);
              },
      ),
    );
  }
}

/// Свитч со подписью слева.
class IltSwitchRow extends StatelessWidget {
  const IltSwitchRow({
    super.key,
    required this.label,
    required this.value,
    this.onChanged,
  });

  final String label;
  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(
            child: Text(label, style: Theme.of(context).textTheme.bodySmall),
          ),
          Switch(
            value: value,
            onChanged: onChanged,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
        ],
      ),
    );
  }
}

/// Радио-карточка выбора (темы, областей экспорта).
class ChoiceCard<T> extends StatelessWidget {
  const ChoiceCard({
    super.key,
    required this.value,
    required this.selected,
    required this.title,
    required this.onChanged,
    this.subtitle,
    this.enabled = true,
  });

  final T value;
  final T selected;
  final String title;
  final String? subtitle;
  final bool enabled;
  final ValueChanged<T>? onChanged;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final active = value == selected;
    return Opacity(
      opacity: enabled ? 1 : 0.5,
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: enabled && onChanged != null ? () => onChanged!(value) : null,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: active ? palette.surface3 : palette.surface1,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: active ? palette.primary : palette.border,
            ),
          ),
          child: Row(
            children: [
              Icon(
                active
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                size: 14,
                color: active ? palette.primary : palette.textMuted,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: theme.textTheme.bodySmall
                        ?.copyWith(color: palette.textPrimary)),
                    if (subtitle != null)
                      Text(subtitle!, style: theme.textTheme.labelSmall),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Карточка-панель для секций и списков.
class PanelCard extends StatelessWidget {
  const PanelCard({super.key, required this.child, this.padding});

  final Widget child;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return Container(
      padding: padding ?? const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: palette.surface1,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: palette.line),
      ),
      child: child,
    );
  }
}
