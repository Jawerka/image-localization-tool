import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/errors.dart';
import '../../model/runtime_pack.dart';
import '../../state/shell_state.dart';
import '../platform.dart';
import '../theme.dart';
import '../widgets.dart';

/// Значения по умолчанию для «Сбросить» (ключи, которыми управляет экран).
const Map<String, Object?> settingsDefaults = {
  'theme': 'system',
  'ui_scale': 100,
  'single_key_shortcuts': true,
  'source_lang': 'en',
  'target_lang': 'ru',
  'reading_order': 'auto',
  'sfx_mode': 'skip',
  'translate_sfx': false,
  'glossary_path': '',
  'llm_base_url': '',
  'llm_model': '',
  'llm_timeout': 300,
  'ocr_backend': 'vlm',
  'translator_backend': 'llm',
  'inpainter_backend': 'lama',
  'device': 'auto',
  'detector_conf': 0.3,
  'min_font_size': 10,
  'max_font_size': 128,
  'text_stroke_ratio': 0.08,
  'text_margin': 0.08,
  'auto_stylized_fonts': true,
  'export_format': 'png',
  'export_jpeg_quality': 90,
  'export_conflict': 'rename',
  'models_dir': '',
  'remote_enabled': false,
  'remote_bind': '0.0.0.0',
  'remote_port': 8765,
};

/// Полноэкранные настройки: девять разделов, черновик с live-preview.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.state});

  final ShellState state;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  static const sections = [
    ('appearance', 'Внешний вид'),
    ('translation', 'Перевод'),
    ('llm', 'Сервер LLM'),
    ('processing', 'Обработка'),
    ('layout', 'Вёрстка'),
    ('export', 'Экспорт'),
    ('models', 'Модели'),
    ('components', 'Компоненты'),
    ('network', 'Сеть'),
    ('about', 'О программе'),
  ];

  late Map<String, dynamic> _baseline;
  late Map<String, dynamic> _draft;
  int _section = 0;
  bool _checking = false;
  bool? _llmOk;
  String _llmReason = '';
  List<String> _llmModels = [];

  ShellState get state => widget.state;

  @override
  void initState() {
    super.initState();
    _baseline = Map<String, dynamic>.of(state.workspace.settings);
    _draft = Map<String, dynamic>.of(_baseline);
    unawaited(state.secondary.refreshModels());
    unawaited(state.secondary.refreshRuntime());
    unawaited(state.secondary.refreshRemote());
  }

  @override
  void dispose() {
    state.workspace.clearPreview();
    super.dispose();
  }

  Map<String, dynamic> get _changed => {
        for (final entry in _draft.entries)
          if (_baseline[entry.key] != entry.value) entry.key: entry.value,
      };

  void _set(String key, Object? value) {
    setState(() => _draft[key] = value);
    if (key == 'theme' || key == 'ui_scale') {
      state.workspace.previewSettings(_draft);
    }
  }

  String _str(String key) => '${_draft[key] ?? ''}';
  num _num(String key, num fallback) {
    final value = _draft[key];
    return value is num ? value : fallback;
  }

  bool _bool(String key, bool fallback) {
    final value = _draft[key];
    return value is bool ? value : fallback;
  }

  Future<void> _apply() async {
    await state.workspace.updateSettings(_changed);
    if (!mounted) return;
    setState(() => _baseline = Map<String, dynamic>.of(_draft));
  }

  Future<void> _ok() async {
    await _apply();
    if (mounted) state.closeOverlay();
  }

  void _cancel() {
    state.workspace.clearPreview();
    state.closeOverlay();
  }

  void _reset() {
    setState(() => _draft = {..._baseline, ...settingsDefaults});
    state.workspace.previewSettings(_draft);
  }

  void _toast(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 3)),
    );
  }

  Future<void> _checkLlm() async {
    final api = state.api;
    final base = _str('llm_base_url').trim();
    if (api == null) return;
    setState(() {
      _checking = true;
      _llmOk = null;
      _llmReason = '';
      _llmModels = [];
    });
    try {
      await state.workspace.updateSettings({
        'llm_base_url': base,
        'llm_model': _str('llm_model'),
      });
      final data = await api.postJson('/api/llm/check');
      if (!mounted) return;
      setState(() {
        _llmOk = data['ok'] == true;
        _llmModels = [
          for (final item in (data['models'] as List? ?? const [])) '$item',
        ];
        _llmReason = '${data['reason'] ?? ''}';
        _baseline['llm_base_url'] = base;
        _baseline['llm_model'] = _str('llm_model');
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _llmOk = false);
        _toast(apiErrorMessage(error));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _llmOk = false);
        _toast('Проверка не удалась: $error');
      }
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _pickModel() async {
    final models = _llmModels;
    final chosen = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('Модель LLM'),
        children: [
          if (models.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Список пуст — нажмите «Проверить»'),
            ),
          for (final model in models)
            SimpleDialogOption(
              onPressed: () => Navigator.of(context).pop(model),
              child: Text(model),
            ),
        ],
      ),
    );
    if (chosen != null) _set('llm_model', chosen);
  }

  Future<void> _setSecret() async {
    final controller = TextEditingController();
    final value = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Ключ API'),
        content: SizedBox(
          width: 380,
          height: kFieldHeight,
          child: TextField(
            controller: controller,
            autofocus: true,
            obscureText: true,
            textAlignVertical: TextAlignVertical.center,
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'ключ',
              contentPadding: EdgeInsets.symmetric(horizontal: 8),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    final api = state.api;
    if (value == null || value.isEmpty || api == null) return;
    try {
      await api.postJson('/api/settings/secret', {'api_key': value});
      state.markApiKeySet();
      _toast('Ключ сохранён');
    } on ApiException catch (error) {
      _toast(apiErrorMessage(error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => Container(
        key: const Key('settings-screen'),
        color: palette.bgPrimary,
        child: Column(
          children: [
            Container(
              height: 46,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(bottom: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  Icon(Icons.settings_outlined, size: 16, color: palette.primary),
                  const SizedBox(width: 8),
                  Text('Настройки', style: theme.textTheme.titleSmall),
                  const SizedBox(width: 12),
                  Text(
                    'черновик · изменения видны сразу',
                    style: theme.textTheme.labelSmall,
                  ),
                  const Spacer(),
                  IconButton(
                    key: const Key('settings-close'),
                    tooltip: 'Закрыть (Esc)',
                    iconSize: 16,
                    onPressed: _cancel,
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    width: 188,
                    color: palette.surface1,
                    child: ListView(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      children: [
                        for (var index = 0; index < sections.length; index++)
                          _navItem(context, index),
                      ],
                    ),
                  ),
                  Expanded(
                    child: SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: Center(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 720),
                          child: _body(context),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(top: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  TextButton(
                    key: const Key('settings-reset'),
                    onPressed: _reset,
                    child: const Text('Сбросить к значениям по умолчанию'),
                  ),
                  const Spacer(),
                  OutlinedButton(
                    key: const Key('settings-apply'),
                    onPressed: _changed.isEmpty ? null : _apply,
                    child: const Text('Применить'),
                  ),
                  const SizedBox(width: 8),
                  TextButton(
                    key: const Key('settings-cancel'),
                    onPressed: _cancel,
                    child: const Text('Отмена'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    key: const Key('settings-ok'),
                    onPressed: _ok,
                    child: const Text('ОК'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _navItem(BuildContext context, int index) {
    final palette = IltPalette.of(context);
    final active = _section == index;
    return InkWell(
      key: Key('settings-nav-${sections[index].$1}'),
      onTap: () => setState(() => _section = index),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        color: active ? palette.surface3 : Colors.transparent,
        child: Text(
          sections[index].$2,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: active ? palette.textPrimary : palette.textMuted,
              ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    switch (sections[_section].$1) {
      case 'appearance':
        return _appearance(context);
      case 'translation':
        return _translation(context);
      case 'llm':
        return _llm(context);
      case 'processing':
        return _processing(context);
      case 'layout':
        return _layout(context);
      case 'export':
        return _export(context);
      case 'models':
        return _models(context);
      case 'components':
        return _components(context);
      case 'network':
        return _network(context);
      default:
        return _about(context);
    }
  }

  Widget _card(BuildContext context, List<Widget> children) => PanelCard(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: children,
        ),
      );

  // --- Разделы ---

  Widget _appearance(BuildContext context) => _card(context, [
        const SectionHeader(
          title: 'Внешний вид',
          lead: 'Окно обновляется сразу, чтобы сравнить варианты до нажатия «ОК».',
        ),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final (value, label) in const [
              ('dark', 'Тёмная'),
              ('light', 'Светлая'),
              ('system', 'Как в системе'),
            ])
              SizedBox(
                width: 200,
                child: ChoiceCard<String>(
                  value: value,
                  selected: '${_draft['theme'] ?? 'system'}',
                  title: label,
                  onChanged: (value) => _set('theme', value),
                ),
              ),
          ],
        ),
        const SizedBox(height: 12),
        FieldRow(
          label: 'Масштаб интерфейса',
          hint: 'Канвас не масштабируется',
          child: Row(
            children: [
              Expanded(
                child: Slider(
                  value: _num('ui_scale', 100).toDouble().clamp(100, 150),
                  min: 100,
                  max: 150,
                  divisions: 5,
                  onChanged: (value) => _set('ui_scale', value.round()),
                ),
              ),
              SizedBox(
                width: 48,
                child: Text(
                  '${_num('ui_scale', 100).round()} %',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
            ],
          ),
        ),
        IltSwitchRow(
          label: 'Однобуквенные клавиши (V, R, B, P, H, M, L, 1–3)',
          value: _bool('single_key_shortcuts', true),
          onChanged: (value) => _set('single_key_shortcuts', value),
        ),
      ]);

  Widget _translation(BuildContext context) => _card(context, [
        const SectionHeader(title: 'Перевод'),
        FieldRow(
          label: 'Язык оригинала',
          child: IltSelect(
            value: '${_draft['source_lang'] ?? 'en'}',
            options: const [
              ('en', 'English'),
              ('ru', 'Русский'),
              ('uk', 'Українська'),
            ],
            onChanged: (value) => _set('source_lang', value),
          ),
        ),
        FieldRow(
          label: 'Язык перевода',
          child: IltSelect(
            value: '${_draft['target_lang'] ?? 'ru'}',
            options: const [
              ('ru', 'Русский'),
              ('en', 'English'),
              ('uk', 'Українська'),
            ],
            onChanged: (value) => _set('target_lang', value),
          ),
        ),
        FieldRow(
          label: 'Порядок чтения',
          child: IltSelect(
            value: '${_draft['reading_order'] ?? 'auto'}',
            options: const [
              ('auto', 'Авто'),
              ('ltr', 'Слева направо'),
              ('rtl', 'Справа налево'),
            ],
            onChanged: (value) => _set('reading_order', value),
          ),
        ),
        FieldRow(
          label: 'Звуки',
          child: IltSelect(
            value: '${_draft['sfx_mode'] ?? 'skip'}',
            options: const [
              ('skip', 'Не трогать'),
              ('replace', 'Заменять текст в звуках'),
            ],
            onChanged: (value) {
              _set('sfx_mode', value);
              _set('translate_sfx', value == 'replace');
            },
          ),
        ),
        FieldRow(
          label: 'Глоссарий по умолчанию',
          hint: 'путь к файлу (иначе — редактор внутри)',
          child: IltTextField(
            value: _str('glossary_path'),
            hint: 'global_glossary.csv',
            onChanged: (value) => _set('glossary_path', value),
          ),
        ),
      ]);

  Widget _llm(BuildContext context) => _card(context, [
        const SectionHeader(
          title: 'Сервер LLM',
          lead: 'OpenAI-совместимый сервер (LM Studio, llama.cpp, Ollama). '
              'Пусто — офлайн RapidOCR + Argos.',
        ),
        FieldRow(
          label: 'Адрес',
          child: IltTextField(
            value: _str('llm_base_url'),
            hint: 'http://127.0.0.1:1234/v1',
            onChanged: (value) => _set('llm_base_url', value),
          ),
        ),
        FieldRow(
          label: 'Модель',
          child: Row(
            children: [
              Expanded(
                child: IltTextField(
                  value: _str('llm_model'),
                  hint: 'qwen2-vl',
                  onChanged: (value) => _set('llm_model', value),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                key: const Key('settings-model-list'),
                onPressed: _pickModel,
                child: const Text('Список…'),
              ),
            ],
          ),
        ),
        FieldRow(
          label: 'Ключ API',
          hint: 'хранится в диспетчере учётных данных Windows, не в JSON',
          child: Row(
            children: [
              Expanded(
                child: Text(
                  state.hasApiKey ? 'задан' : 'не задан',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              OutlinedButton(
                key: const Key('settings-secret'),
                onPressed: _setSecret,
                child: const Text('Задать…'),
              ),
            ],
          ),
        ),
        Row(
          children: [
            FilledButton(
              key: const Key('settings-llm-check'),
              onPressed: _checking ? null : _checkLlm,
              child: Text(_checking ? 'Проверка…' : 'Проверить'),
            ),
            const SizedBox(width: 12),
            if (_llmOk == true)
              Text(
                _llmModels.isEmpty
                    ? 'Сервер отвечает'
                    : 'Моделей: ${_llmModels.length}',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: IltPalette.of(context).textSuccess,
                    ),
              ),
            if (_llmOk == false)
              Expanded(
                child: Text(
                  _llmReason.isEmpty || _llmReason == 'empty'
                      ? 'Адрес пуст или сервер недоступен'
                      : 'Недоступен: $_llmReason',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: IltPalette.of(context).textError,
                      ),
                ),
              ),
          ],
        ),
      ]);

  Widget _processing(BuildContext context) => _card(context, [
        const SectionHeader(title: 'Обработка'),
        FieldRow(
          label: 'Распознавание',
          child: IltSelect(
            value: '${_draft['ocr_backend'] ?? 'vlm'}',
            options: const [('vlm', 'VLM'), ('rapid', 'RapidOCR')],
            onChanged: (value) => _set('ocr_backend', value),
          ),
        ),
        FieldRow(
          label: 'Перевод',
          child: IltSelect(
            value: '${_draft['translator_backend'] ?? 'llm'}',
            options: const [('llm', 'LLM'), ('argos', 'Argos')],
            onChanged: (value) => _set('translator_backend', value),
          ),
        ),
        FieldRow(
          label: 'Очистка',
          child: IltSelect(
            value: '${_draft['inpainter_backend'] ?? 'lama'}',
            options: const [('lama', 'LaMa'), ('opencv', 'Заливка (OpenCV)')],
            onChanged: (value) => _set('inpainter_backend', value),
          ),
        ),
        FieldRow(
          label: 'Устройство',
          child: IltSelect(
            value: '${_draft['device'] ?? 'auto'}',
            options: const [('auto', 'Авто'), ('gpu', 'GPU'), ('cpu', 'CPU')],
            onChanged: (value) => _set('device', value),
          ),
        ),
        FieldRow(
          label: 'Порог детектора',
          child: IltNumberField(
            value: _num('detector_conf', 0.3),
            min: 0,
            max: 1,
            decimals: true,
            onChanged: (value) => _set('detector_conf', value),
          ),
        ),
      ]);

  Widget _layout(BuildContext context) => _card(context, [
        const SectionHeader(title: 'Вёрстка'),
        FieldRow(
          label: 'Минимальный кегль',
          child: IltNumberField(
            value: _num('min_font_size', 10),
            min: 4,
            max: 200,
            onChanged: (value) => _set('min_font_size', value),
          ),
        ),
        FieldRow(
          label: 'Максимальный кегль',
          child: IltNumberField(
            value: _num('max_font_size', 128),
            min: 4,
            max: 400,
            onChanged: (value) => _set('max_font_size', value),
          ),
        ),
        FieldRow(
          label: 'Ореол, доля кегля',
          child: IltNumberField(
            value: _num('text_stroke_ratio', 0.08),
            min: 0,
            max: 1,
            decimals: true,
            onChanged: (value) => _set('text_stroke_ratio', value),
          ),
        ),
        FieldRow(
          label: 'Запас от края баллона',
          child: IltNumberField(
            value: _num('text_margin', 0.08),
            min: 0,
            max: 1,
            decimals: true,
            onChanged: (value) => _set('text_margin', value),
          ),
        ),
        IltSwitchRow(
          label: 'Автоподбор стилизованных шрифтов для звуков',
          value: _bool('auto_stylized_fonts', true),
          onChanged: (value) => _set('auto_stylized_fonts', value),
        ),
      ]);

  Widget _export(BuildContext context) => _card(context, [
        const SectionHeader(title: 'Экспорт'),
        FieldRow(
          label: 'Формат',
          child: IltSelect(
            value: '${_draft['export_format'] ?? 'png'}',
            options: const [('png', 'PNG'), ('jpg', 'JPG')],
            onChanged: (value) => _set('export_format', value),
          ),
        ),
        FieldRow(
          label: 'Качество JPG',
          child: IltNumberField(
            value: _num('export_jpeg_quality', 90),
            min: 1,
            max: 100,
            onChanged: (value) => _set('export_jpeg_quality', value),
          ),
        ),
        FieldRow(
          label: 'Совпадение имён',
          child: IltSelect(
            value: '${_draft['export_conflict'] ?? 'rename'}',
            options: const [
              ('rename', 'Добавить номер'),
              ('overwrite', 'Перезаписать'),
              ('skip', 'Пропустить'),
            ],
            onChanged: (value) => _set('export_conflict', value),
          ),
        ),
      ]);

  Widget _models(BuildContext context) {
    final secondary = state.secondary;
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final titles = {
      'detector': 'Детектор (RT-DETR)',
      'lama': 'LaMa (очистка)',
      'font': 'Шрифты (OFL)',
    };
    final missing = [
      for (final model in secondary.models)
        if (!model.present) model.kind,
    ];
    return _card(context, [
      const SectionHeader(
        title: 'Модели',
        lead: 'Без них не работает распознавание и очистка.',
      ),
      for (final model in secondary.models)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(
            children: [
              SizedBox(
                width: 190,
                child: Text(
                  titles[model.kind] ?? model.kind,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: palette.textPrimary),
                ),
              ),
              Expanded(
                child: model.downloading
                    ? Row(
                        children: [
                          Expanded(
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(2),
                              child: LinearProgressIndicator(
                                value: model.percent,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            model.percent == null
                                ? _bytes(model.bytesDone)
                                : '${(model.percent! * 100).round()} %',
                            style: theme.textTheme.labelSmall,
                          ),
                        ],
                      )
                    : Text(
                        model.error.isNotEmpty
                            ? 'ошибка: ${model.error}'
                            : (model.present ? 'Готово' : 'не скачано'),
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: model.present
                              ? palette.textSuccess
                              : (model.error.isNotEmpty
                                  ? palette.textError
                                  : palette.textMuted),
                        ),
                      ),
              ),
              const SizedBox(width: 8),
              if (!model.present && !model.downloading)
                OutlinedButton(
                  key: Key('model-download-${model.kind}'),
                  onPressed: () => secondary.startDownload(model.kind),
                  child: const Text('Скачать'),
                ),
            ],
          ),
        ),
      const SizedBox(height: 8),
      Row(
        children: [
          FilledButton(
            key: const Key('models-download-missing'),
            onPressed: missing.isEmpty
                ? null
                : () {
                    for (final kind in missing) {
                      secondary.startDownload(kind);
                    }
                  },
            child: const Text('Скачать недостающие'),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            key: const Key('models-open-folder'),
            onPressed: () => openFolder(state.modelsDir),
            child: const Text('Открыть папку моделей'),
          ),
        ],
      ),
    ]);
  }

  Widget _components(BuildContext context) {
    final secondary = state.secondary;
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final runtime = secondary.runtime;
    final busy = runtime.packs.any((pack) => pack.downloading);
    return _card(context, [
      const SectionHeader(
        title: 'Компоненты',
        lead: 'PyTorch ускоряет очистку на NVIDIA, Argos переводит офлайн. '
            'Пакеты не входят в установщик и скачиваются отдельно.',
      ),
      if (runtime.reason.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Text(
            runtime.reason,
            style: theme.textTheme.labelSmall?.copyWith(color: palette.textMuted),
          ),
        ),
      if (runtime.packs.isEmpty)
        Text(
          'Список компонентов недоступен.',
          style: theme.textTheme.labelSmall,
        )
      else
        for (final pack in runtime.packs)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                SizedBox(
                  width: 190,
                  child: Text(
                    pack.title,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: palette.textPrimary),
                  ),
                ),
                Expanded(
                  child: pack.downloading
                      ? Row(
                          children: [
                            Expanded(
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(2),
                                child: LinearProgressIndicator(
                                  value: pack.percent,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              pack.percent == null
                                  ? _bytes(pack.done)
                                  : '${(pack.percent! * 100).round()} %',
                              style: theme.textTheme.labelSmall,
                            ),
                          ],
                        )
                      : Text(
                          pack.failed
                              ? 'ошибка: ${pack.error}'
                              : (pack.installed
                                  ? 'Готово · ${_bytes(pack.installedBytes)}'
                                  : 'не скачано · ${_bytes(pack.sizeBytes)}'),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.labelSmall?.copyWith(
                            color: pack.installed
                                ? palette.textSuccess
                                : (pack.failed
                                    ? palette.textError
                                    : palette.textMuted),
                          ),
                        ),
                ),
                const SizedBox(width: 8),
                if (!pack.installed && !pack.downloading)
                  OutlinedButton(
                    key: Key('component-download-${pack.id}'),
                    onPressed: (busy || _torchConflict(pack) != null)
                        ? null
                        : () => secondary.startRuntimeDownload(pack.id),
                    child: const Text('Скачать'),
                  ),
                if (pack.installed)
                  OutlinedButton(
                    key: Key('component-remove-${pack.id}'),
                    onPressed: () => secondary.removeRuntimePack(pack.id),
                    child: const Text('Удалить'),
                  ),
              ],
            ),
          ),
      const SizedBox(height: 8),
      Text(
        runtime.torchReady
            ? 'PyTorch подключён · устройство: ${runtime.deviceEffective}'
            : 'PyTorch не подключён — очистка идёт через OpenCV.',
        style: theme.textTheme.labelSmall?.copyWith(
          color: runtime.torchReady ? palette.textSuccess : palette.textMuted,
        ),
      ),
    ]);
  }

  /// Название второго torch-пака, если он уже стоит или качается.
  String? _torchConflict(RuntimePack pack) {
    if (pack.kind != 'torch') return null;
    final otherId = pack.id == 'torch-cpu' ? 'torch-cu128' : 'torch-cpu';
    final other = state.secondary.runtime.pack(otherId);
    if (other != null && (other.installed || other.downloading)) {
      return other.title;
    }
    return null;
  }

  Widget _network(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final remote = state.secondary.remote;
    return _card(context, [
      const SectionHeader(
        title: 'Доступ по сети',
        lead: 'Страницы открываются в браузере соседнего устройства.',
      ),
      IltSwitchRow(
        label: 'Разрешить доступ в локальной сети',
        value: _bool('remote_enabled', false),
        onChanged: (value) => _set('remote_enabled', value),
      ),
      FieldRow(
        label: 'Адрес',
        child: IltTextField(
          value: '${_draft['remote_bind'] ?? '0.0.0.0'}',
          onChanged: (value) => _set('remote_bind', value),
        ),
      ),
      FieldRow(
        label: 'Порт',
        child: IltNumberField(
          value: _num('remote_port', 8765),
          min: 1,
          max: 65535,
          onChanged: (value) => _set('remote_port', value),
        ),
      ),
      Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: palette.surface2,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: palette.border),
            ),
            child: Text(
              remote.enabled
                  ? 'слушает ${remote.addresses.isEmpty ? '…' : remote.addresses.join(', ')}'
                  : 'не слушает',
              style: theme.textTheme.labelSmall,
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            key: const Key('network-restart'),
            onPressed: () async {
              await state.restartSidecar();
              await state.secondary.refreshRemote();
              _toast('API перезапущен');
            },
            child: const Text('Перезапустить API'),
          ),
        ],
      ),
      const SizedBox(height: 8),
      Text(
        'Изменения сети применяются при следующем запуске API. Брандмауэр '
        'Windows может блокировать порт; передача идёт по HTTP без шифрования.',
        style: theme.textTheme.labelSmall,
      ),
    ]);
  }

  Widget _about(BuildContext context) {
    final theme = Theme.of(context);
    final version = '${state.bootstrap?['version'] ?? ''}';
    final paths = state.bootstrap?['paths'];
    final settingsPath = paths is Map ? '${paths['settings'] ?? ''}' : '';
    final dataPath = paths is Map ? '${paths['data'] ?? ''}' : '';
    return _card(context, [
      const SectionHeader(title: 'О программе'),
      FieldRow(label: 'Версия', child: Text(version, style: theme.textTheme.bodySmall)),
      FieldRow(
        label: 'Настройки',
        child: Text(
          settingsPath,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.labelSmall,
        ),
      ),
      FieldRow(
        label: 'Данные и лог',
        child: Text(
          dataPath,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.labelSmall,
        ),
      ),
      const SizedBox(height: 8),
      Row(
        children: [
          OutlinedButton(
            key: const Key('about-open-log'),
            onPressed: state.logPath == null
                ? null
                : () => openPath(state.logPath!),
            child: const Text('Открыть лог'),
          ),
          const SizedBox(width: 8),
          OutlinedButton(
            key: const Key('about-open-data'),
            onPressed: state.dataDir == null
                ? null
                : () => openFolder(state.dataDir!),
            child: const Text('Открыть папку данных'),
          ),
        ],
      ),
    ]);
  }

  static String _bytes(int value) {
    if (value >= 1024 * 1024) {
      return '${(value / (1024 * 1024)).toStringAsFixed(1)} МБ';
    }
    if (value >= 1024) return '${(value / 1024).toStringAsFixed(0)} КБ';
    return '$value Б';
  }
}
