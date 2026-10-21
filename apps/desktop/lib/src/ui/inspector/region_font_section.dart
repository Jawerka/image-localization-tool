import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../model/page_document.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'inspector_controls.dart';
import 'sfx_section.dart';

/// Вкладка «Шрифт»: семейство, кегль, чернила, цвета, обводка,
/// стили проекта и буфер стиля (024).
class RegionFontSection extends StatefulWidget {
  const RegionFontSection({
    super.key,
    required this.viewer,
    required this.region,
  });

  final ViewerState viewer;
  final Region region;

  @override
  State<RegionFontSection> createState() => _RegionFontSectionState();
}

class _RegionFontSectionState extends State<RegionFontSection> {
  final _size = TextEditingController();
  final _sizeFocus = FocusNode();
  final _fill = TextEditingController();
  final _fillFocus = FocusNode();
  final _stroke = TextEditingController();
  final _strokeFocus = FocusNode();
  final _width = TextEditingController();
  final _widthFocus = FocusNode();

  String get _id => widget.region.id;

  Map<String, dynamic> get _style {
    final raw = widget.region.data['style'];
    return raw is Map ? raw.cast<String, dynamic>() : const {};
  }

  @override
  void initState() {
    super.initState();
    _sizeFocus.addListener(() {
      if (!_sizeFocus.hasFocus) _commitSize();
    });
    _fillFocus.addListener(() {
      if (!_fillFocus.hasFocus) _commitFill();
    });
    _strokeFocus.addListener(() {
      if (!_strokeFocus.hasFocus) _commitStroke();
    });
    _widthFocus.addListener(() {
      if (!_widthFocus.hasFocus) _commitWidth();
    });
  }

  @override
  void dispose() {
    _size.dispose();
    _sizeFocus.dispose();
    _fill.dispose();
    _fillFocus.dispose();
    _stroke.dispose();
    _strokeFocus.dispose();
    _width.dispose();
    _widthFocus.dispose();
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
    final auto = (style['font_size'] as num?)?.round() ?? 0;
    final family = viewer.fontFamilyFor('${style['font_id'] ?? ''}');

    _sync(_size, _sizeText(style), _sizeFocus);
    _sync(_fill, rgbToHex(style['fill_rgb']), _fillFocus);
    _sync(_stroke, rgbToHex(style['stroke_rgb']), _strokeFocus);
    _sync(_width, _widthText(style), _widthFocus);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InspectorField(
          label: 'Шрифт',
          child: Row(
            children: [
              IconButton(
                key: const Key('style-font-prev'),
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: () => _navigateFont(-1),
                icon: const Icon(Icons.chevron_left),
              ),
              Expanded(child: _fontSelect(style, family)),
              IconButton(
                key: const Key('style-font-next'),
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: () => _navigateFont(1),
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
        ),
        Text(
          _sampleText(region),
          key: const Key('style-font-sample'),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 16,
            color: IltPalette.of(context).textPrimary,
            fontFamily: family,
          ),
        ),
        InspectorField(
          label: 'Кегль',
          child: Row(
            children: [
              IconButton(
                key: const Key('style-size-minus'),
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: () => _stepFont(-1),
                icon: const Icon(Icons.remove),
              ),
              Expanded(
                child: InspectorInput(
                  controller: _size,
                  focusNode: _sizeFocus,
                  numeric: true,
                  hint: auto > 0 ? 'авто · $auto' : 'авто',
                  onSubmitted: (_) => _commitSize(),
                ),
              ),
              IconButton(
                key: const Key('style-size-plus'),
                visualDensity: VisualDensity.compact,
                iconSize: 16,
                onPressed: () => _stepFont(1),
                icon: const Icon(Icons.add),
              ),
            ],
          ),
        ),
        Text(
          'от ${viewer.fontMin} до ${viewer.fontMax}, пусто — авто',
          style: Theme.of(context).textTheme.labelSmall,
        ),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Wrap(
            spacing: 4,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              InkWell(
                key: const Key('style-uppercase'),
                onTap: () => viewer.toggleRegionUppercase(_id),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SizedBox(
                      width: 28,
                      height: 24,
                      child: Checkbox(
                        value: style['uppercase'] == true,
                        onChanged: (_) => viewer.toggleRegionUppercase(_id),
                        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        visualDensity: VisualDensity.compact,
                      ),
                    ),
                    Text(
                      'ПРОПИСНЫЕ',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ],
                ),
              ),
              InspectorAction(
                key: const Key('style-ink-black'),
                label: 'Чёрный',
                active: _isInk(style, dark: true),
                onPressed: () => viewer.setRegionInk(_id, white: false),
              ),
              InspectorAction(
                key: const Key('style-ink-white'),
                label: 'Белый',
                active: _isInk(style, dark: false),
                onPressed: () => viewer.setRegionInk(_id, white: true),
              ),
            ],
          ),
        ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: InspectorField(
                label: 'Заливка',
                child: InspectorInput(
                  key: const Key('style-fill'),
                  controller: _fill,
                  focusNode: _fillFocus,
                  onSubmitted: (_) => _commitFill(),
                ),
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: InspectorField(
                label: 'Обводка',
                child: InspectorInput(
                  key: const Key('style-stroke'),
                  controller: _stroke,
                  focusNode: _strokeFocus,
                  onSubmitted: (_) => _commitStroke(),
                ),
              ),
            ),
            const SizedBox(width: 6),
            SizedBox(
              width: 64,
              child: InspectorField(
                label: 'Толщина',
                child: InspectorInput(
                  key: const Key('style-stroke-width'),
                  controller: _width,
                  focusNode: _widthFocus,
                  numeric: true,
                  onSubmitted: (_) => _commitWidth(),
                ),
              ),
            ),
          ],
        ),
        Wrap(
          spacing: 4,
          runSpacing: 4,
          children: [
            InspectorAction(
              key: const Key('style-copy'),
              label: 'Копировать весь стиль',
              icon: Icons.copy,
              onPressed: viewer.copyStyle,
            ),
            InspectorAction(
              key: const Key('style-paste'),
              label: 'Вставить стиль',
              icon: Icons.paste,
              onPressed: viewer.hasStyleClipboard ? viewer.pasteStyle : null,
            ),
          ],
        ),
        const SizedBox(height: 6),
        InspectorLabel(
          'Стили проекта',
          trailing: TextButton(
            key: const Key('style-save-project'),
            onPressed: viewer.saveProjectStyle,
            style: TextButton.styleFrom(
              visualDensity: VisualDensity.compact,
              minimumSize: const Size(0, 22),
              padding: const EdgeInsets.symmetric(horizontal: 6),
            ),
            child: const Text('Сохранить стиль'),
          ),
        ),
        if (viewer.styleLibrary.isEmpty)
          Text(
            'Сохранённых стилей пока нет.',
            style: Theme.of(context).textTheme.labelSmall,
          )
        else
          Wrap(
            spacing: 4,
            runSpacing: 4,
            children: [
              for (final item in viewer.styleLibrary)
                InspectorAction(
                  key: Key('style-project-${item['name']}'),
                  label: '${item['name'] ?? 'Стиль'}',
                  onPressed: () {
                    final preset = item['style'];
                    if (preset is Map) {
                      viewer.applyStyleToRegion(
                        _id,
                        preset.cast<String, dynamic>(),
                      );
                    }
                  },
                ),
            ],
          ),
        if (region.isSfx) SfxFontSection(viewer: viewer, region: region),
      ],
    );
  }

  String _sampleText(Region region) {
    final translation = '${region.data['translation'] ?? ''}'.trim();
    if (translation.isNotEmpty) return translation;
    final text = '${region.data['text'] ?? ''}'.trim();
    return text.isEmpty ? 'Я голоден!' : text;
  }

  bool _isInk(Map<String, dynamic> style, {required bool dark}) {
    final rgb = style['fill_rgb'];
    final mean = rgb is List && rgb.length >= 3
        ? ((rgb[0] as num? ?? 0) +
                  (rgb[1] as num? ?? 0) +
                  (rgb[2] as num? ?? 0)) /
              3
        : 0;
    return dark ? mean <= 127.5 : mean > 127.5;
  }

  Widget _fontSelect(Map<String, dynamic> style, String? family) {
    final viewer = widget.viewer;
    final current = '${style['font_id'] ?? ''}';
    final options = <(String, String, String?)>[
      ('', 'По умолчанию', null),
      for (final font in viewer.fonts)
        (
          '${font['id'] ?? ''}',
          '${font['family'] ?? font['id'] ?? ''}',
          viewer.fontFamilyFor('${font['id'] ?? ''}'),
        ),
    ];
    final known = options.any((item) => item.$1 == current);
    return SizedBox(
      height: kFieldHeight,
      child: DropdownButtonFormField<String>(
        key: const Key('style-font-select'),
        initialValue: known ? current : '',
        isDense: true,
        decoration: InputDecoration(
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8),
          filled: true,
          fillColor: IltPalette.of(context).input,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(6),
            borderSide: BorderSide(color: IltPalette.of(context).border),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(6),
            borderSide: BorderSide(color: IltPalette.of(context).border),
          ),
        ),
        style: Theme.of(
          context,
        ).textTheme.bodySmall?.copyWith(fontFamily: family),
        dropdownColor: IltPalette.of(context).surface2,
        items: [
          for (final (value, label, itemFamily) in options)
            DropdownMenuItem(
              value: value,
              child: Text(label, style: TextStyle(fontFamily: itemFamily)),
            ),
        ],
        onChanged: (value) => viewer.setRegionFontId(_id, value ?? ''),
      ),
    );
  }

  void _navigateFont(int step) {
    final viewer = widget.viewer;
    final options = <String>[
      '',
      for (final font in viewer.fonts) '${font['id'] ?? ''}',
    ];
    final current = '${_style['font_id'] ?? ''}';
    final index = options.contains(current) ? options.indexOf(current) : 0;
    final next = (index + step + options.length) % options.length;
    viewer.setRegionFontId(_id, options[next]);
  }

  int _fontBase() {
    final digits = _size.text.replaceAll(RegExp(r'\D'), '');
    if (digits.isNotEmpty) return int.tryParse(digits) ?? 0;
    return (_style['font_size'] as num?)?.round() ?? 0;
  }

  void _stepFont(int direction) {
    final viewer = widget.viewer;
    var base = _fontBase();
    if (base <= 0) base = viewer.fontMin;
    final step = HardwareKeyboard.instance.isShiftPressed ? 10 : 1;
    final next = base + direction * step;
    _size.text = '$next';
    viewer.setRegionFontSize(_id, next);
  }

  void _commitSize() {
    final digits = _size.text.replaceAll(RegExp(r'\D'), '');
    final value = digits.isEmpty ? 0 : int.tryParse(digits) ?? 0;
    widget.viewer.setRegionFontSize(_id, value);
  }

  void _commitFill() {
    final rgb = hexToRgb(_fill.text);
    if (rgb == null) {
      _fill.text = rgbToHex(_style['fill_rgb']);
      return;
    }
    widget.viewer.setRegionFillRgb(_id, rgb);
  }

  void _commitStroke() {
    final rgb = hexToRgb(_stroke.text);
    if (rgb == null) {
      _stroke.text = rgbToHex(_style['stroke_rgb']);
      return;
    }
    widget.viewer.setRegionStrokeRgb(_id, rgb);
  }

  void _commitWidth() {
    final value = num.tryParse(_width.text.replaceAll(',', '.'));
    widget.viewer.setRegionStrokeWidth(_id, value ?? 0);
  }

  String _sizeText(Map<String, dynamic> style) {
    final value = (style['font_size_override'] as num?)?.toInt() ?? 0;
    return value > 0 ? '$value' : '';
  }

  String _widthText(Map<String, dynamic> style) {
    final value = (style['stroke_width'] as num?)?.toDouble() ?? 0;
    return value > 0
        ? (value == value.roundToDouble() ? '${value.round()}' : '$value')
        : '';
  }
}
