import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/errors.dart';
import '../../model/runtime_pack.dart';
import '../../state/shell_state.dart';
import '../theme.dart';
import '../widgets.dart';
import '../preparation_panel.dart';

/// Мастер первого запуска: тема, модели, LLM, языки.
class FirstRunScreen extends StatefulWidget {
  const FirstRunScreen({super.key, required this.state});

  final ShellState state;

  @override
  State<FirstRunScreen> createState() => _FirstRunScreenState();
}

class _FirstRunScreenState extends State<FirstRunScreen> {
  List<String> get steps => ['Тема', 'Перевод', if (_draft['translator_backend'] != 'argos') 'Сервер LLM', 'Языки', 'Подготовка'];

  int _step = 0;
  late Map<String, dynamic> _draft;
  bool _checking = false;
  bool? _llmOk;
  String _llmReason = '';
  List<String> _llmModels = [];

  ShellState get state => widget.state;

  @override
  void initState() {
    super.initState();
    final settings = state.workspace.settings;
    _draft = {
      'theme': settings['theme'] ?? 'system',
      'source_lang': settings['source_lang'] ?? 'en',
      'target_lang': settings['target_lang'] ?? 'ru',
      'llm_base_url': settings['llm_base_url'] ?? '',
      'llm_model': settings['llm_model'] ?? '',
      'api_key': '',
      'translator_backend': settings['translator_backend'] ?? 'llm',
      'device': settings['device'] ?? 'auto',
      'inpainter_backend': settings['inpainter_backend'] ?? 'lama',
      'models_dir': settings['models_dir'] ?? '',
    };
    unawaited(state.secondary.refreshModels());
    unawaited(state.secondary.refreshRuntime());
  }

  void _set(String key, Object? value) {
    setState(() => _draft[key] = value);
    if (key == 'theme') state.workspace.previewSettings(_draft);
  }

  Future<void> _skip() async {
    await state.workspace.completeFirstRun(const {});
    state.dismissFirstRun();
  }

  Future<void> _finish() async {
    await _saveApiKey();
    await state.workspace.completeFirstRun(_draft);
    state.dismissFirstRun();
  }

  /// Сохранить ключ из мастера в keyring (в настройках JSON он не хранится).
  Future<void> _saveApiKey() async {
    final api = state.api;
    final key = '${_draft['api_key'] ?? ''}'.trim();
    if (api == null || key.isEmpty) return;
    try {
      await api.postJson('/api/settings/secret', {'api_key': key});
      state.markApiKeySet();
      _draft['api_key'] = '';
    } catch (error) {
      if (mounted) {
        setState(() {
          _llmOk = false;
          _llmReason = error is ApiException
              ? apiErrorMessage(error)
              : 'Ключ не сохранён: $error';
        });
      }
    }
  }

  Future<void> _checkLlm() async {
    final api = state.api;
    final base = '${_draft['llm_base_url'] ?? ''}'.trim();
    if (api == null) return;
    setState(() {
      _checking = true;
      _llmOk = null;
      _llmReason = '';
    });
    try {
      await _saveApiKey();
      await state.workspace.updateSettings({'llm_base_url': base, 'llm_model': '${_draft['llm_model'] ?? ''}'});
      final data = await api.postJson('/api/llm/check');
      if (!mounted) return;
      setState(() {
        _llmOk = data['ok'] == true;
        _llmModels = [
          for (final item in (data['models'] as List? ?? const [])) '$item',
        ];
        _llmReason = '${data['reason'] ?? ''}';
      });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _llmOk = false);
        if (error.statusCode != 400) _llmReason = apiErrorMessage(error);
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _llmOk = false;
          _llmReason = '$error';
        });
      }
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => Container(
        key: const Key('first-run-screen'),
        color: palette.bgPrimary,
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(bottom: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  Icon(Icons.auto_awesome, size: 18, color: palette.primary),
                  const SizedBox(width: 10),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Добро пожаловать', style: theme.textTheme.titleSmall),
                      Text(
                        'подготовим нужные компоненты · прогресс загрузки сохранится',
                        style: theme.textTheme.labelSmall,
                      ),
                    ],
                  ),
                  const Spacer(),
                  TextButton(
                    key: const Key('first-run-skip'),
                    onPressed: _skip,
                    child: const Text('Пропустить всё'),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 16),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var index = 0; index < steps.length; index++) ...[
                    if (index > 0)
                      Container(
                        width: 40,
                        height: 1,
                        margin: const EdgeInsets.symmetric(horizontal: 8),
                        color: palette.line,
                      ),
                    Row(
                      children: [
                        Container(
                          width: 20,
                          height: 20,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: index <= _step
                                ? palette.primary
                                : palette.surface3,
                          ),
                          child: index < _step
                              ? Icon(
                                  Icons.check,
                                  size: 12,
                                  color: palette.primaryFg,
                                )
                              : Text(
                                  '${index + 1}',
                                  style: theme.textTheme.labelSmall?.copyWith(
                                    color: index <= _step
                                        ? palette.primaryFg
                                        : palette.textMuted,
                                  ),
                                ),
                        ),
                        const SizedBox(width: 6),
                        Text(steps[index], style: theme.textTheme.labelSmall),
                      ],
                    ),
                  ],
                ],
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 640),
                    child: switch (_step) {
                      0 => _themeStep(context),
                      1 => _modeStep(context),
                      2 => _draft['translator_backend'] == 'argos' ? _languagesStep(context) : _llmStep(context),
                      3 => _draft['translator_backend'] == 'argos' ? _preparationStep(context) : _languagesStep(context),
                      _ => _preparationStep(context),
                    },
                  ),
                ),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              decoration: BoxDecoration(
                color: palette.surface1,
                border: Border(top: BorderSide(color: palette.line)),
              ),
              child: Row(
                children: [
                  TextButton(
                    key: const Key('first-run-back'),
                    onPressed: _step == 0
                        ? null
                        : () => setState(() => _step -= 1),
                    child: const Text('Назад'),
                  ),
                  const Spacer(),
                  Text(
                    'Шаг ${_step + 1} из ${steps.length}',
                    style: theme.textTheme.labelSmall,
                  ),
                  const Spacer(),
                  FilledButton(
                    key: const Key('first-run-next'),
                    onPressed: _step == steps.length - 1
                        ? _finish
                        : () => setState(() => _step += 1),
                    child: Text(_step == steps.length - 1 ? 'Готово' : 'Далее'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _card(BuildContext context, List<Widget> children) => PanelCard(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: children,
        ),
      );

  Widget _themeStep(BuildContext context) => _card(context, [
        const SectionHeader(
          title: 'Тема',
          lead: 'Окно обновится сразу — можно сравнить варианты.',
        ),
        Row(
          children: [
            for (final (value, label) in const [
              ('dark', 'Тёмная'),
              ('light', 'Светлая'),
              ('system', 'Как в системе'),
            ]) ...[
              Expanded(
                child: ChoiceCard<String>(
                  value: value,
                  selected: '${_draft['theme'] ?? 'system'}',
                  title: label,
                  onChanged: (value) => _set('theme', value),
                ),
              ),
              if (value != 'system') const SizedBox(width: 8),
            ],
          ],
        ),
      ]);

  Widget _modeStep(BuildContext context) => _card(context, [
    const SectionHeader(title: 'Способ перевода', lead: 'Нужные компоненты будут выбраны автоматически.'),
    SegmentedButton<String>(
      segments: const [
        ButtonSegment(value: 'llm', label: Text('Сервер LLM')),
        ButtonSegment(value: 'argos', label: Text('Оффлайн')),
      ],
      selected: {'${_draft['translator_backend']}'},
      onSelectionChanged: (values) => _set('translator_backend', values.first),
    ),
    const SizedBox(height: 12),
    const Text('Оффлайн-перевод работает после загрузки языковой модели. Для LLM укажите свой сервер.'),
  ]);

  Widget _preparationStep(BuildContext context) => _card(context, [
    PreparationPanel(state: state.secondary, selection: _draft, onDeviceChanged: (value) => _set('device', value)),
    const SizedBox(height: 12),
    Material(type: MaterialType.transparency, child: ExpansionTile(
      title: const Text('Дополнительные настройки компонентов'),
      children: [_componentsStep(context)],
    )),
  ]);

  /// Конфликт torch-паков: cpu и cu128 не ставятся одновременно.
  String? _torchConflict(RuntimePack pack) {
    if (pack.kind != 'torch') return null;
    for (final other in state.secondary.runtime.packs) {
      if (other.kind == 'torch' && other.id != pack.id && other.downloading) {
        return 'дождитесь завершения «${other.title}»';
      }
    }
    return null;
  }

  Widget _componentsStep(BuildContext context) {
    final secondary = state.secondary;
    final runtime = secondary.runtime;
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return _card(context, [
      const SectionHeader(
        title: 'Компоненты',
        lead: 'PyTorch ускоряет очистку (NVIDIA), Argos даёт офлайн-перевод. '
            'Ставятся отдельно — можно пропустить и вернуться в настройках.',
      ),
      if (runtime.reason.isNotEmpty) ...[
        Text(
          runtime.reason,
          style: theme.textTheme.labelSmall?.copyWith(color: palette.textMuted),
        ),
        const SizedBox(height: 8),
      ],
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
                  width: 210,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        pack.title,
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: palette.textPrimary),
                      ),
                      Text(
                        '${_formatBytes(pack.sizeBytes)}'
                        '${pack.source.isNotEmpty ? ' · ${pack.source}' : ''}'
                        ' · ${_formatEta(pack.sizeBytes)}'
                        '${pack.recommended ? ' · рекомендовано' : ''}',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: pack.recommended
                              ? palette.primary
                              : palette.textMuted,
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(child: _runtimeStatus(context, pack)),
                const SizedBox(width: 8),
                _runtimeAction(context, pack),
              ],
            ),
          ),
      if ((secondary.errorText ?? '').isNotEmpty) ...[
        const SizedBox(height: 6),
        Text(
          'Ошибка: ${secondary.errorText}',
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.labelSmall?.copyWith(color: palette.textError),
        ),
      ],
      const SizedBox(height: 6),
      Text(
        'Большие компоненты качаются в фоне — прогресс виден здесь и в настройках. '
        'Смена компонента применится при следующей обработке.',
        style: theme.textTheme.labelSmall,
      ),
    ]);
  }

  Widget _runtimeStatus(BuildContext context, RuntimePack pack) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    if (pack.downloading) {
      return Row(
        children: [
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: LinearProgressIndicator(value: pack.percent),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            pack.percent == null
                ? _formatBytes(pack.done)
                : '${(pack.percent! * 100).round()} %',
            style: theme.textTheme.labelSmall,
          ),
        ],
      );
    }
    final text = pack.failed
        ? 'ошибка: ${pack.error}'
        : (pack.installed ? 'установлено' : 'не установлено');
    return Text(
      text,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
      style: theme.textTheme.labelSmall?.copyWith(
        color: pack.installed
            ? palette.textSuccess
            : (pack.failed ? palette.textError : palette.textMuted),
      ),
    );
  }

  Widget _runtimeAction(BuildContext context, RuntimePack pack) {
    final palette = IltPalette.of(context);
    if (pack.installed) {
      return Icon(Icons.check, size: 14, color: palette.textSuccess);
    }
    if (pack.downloading) return const SizedBox(width: 86);
    final conflict = _torchConflict(pack);
    if (conflict != null) {
      final theme = Theme.of(context);
      return SizedBox(
        width: 200,
        child: Text(
          conflict,
          textAlign: TextAlign.right,
          style: theme.textTheme.labelSmall?.copyWith(color: palette.textMuted),
        ),
      );
    }
    return OutlinedButton(
      key: Key('wizard-runtime-download-${pack.id}'),
      onPressed: () => state.secondary.startRuntimeDownload(pack.id),
      child: const Text('Скачать'),
    );
  }

  Widget _llmStep(BuildContext context) {
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    return _card(context, [
      const SectionHeader(
        title: 'Сервер LLM',
        lead: 'OpenAI-совместимый сервер (LM Studio, llama.cpp, Ollama). '
            'Можно пропустить — офлайн-режим RapidOCR + Argos.',
      ),
      FieldRow(
        label: 'Адрес',
        child: IltTextField(
          value: '${_draft['llm_base_url'] ?? ''}',
          hint: 'http://127.0.0.1:1234/v1',
          onChanged: (value) => _set('llm_base_url', value),
        ),
      ),
      FieldRow(
        label: 'Модель',
        child: _llmModels.isEmpty
            ? IltTextField(
                value: '${_draft['llm_model'] ?? ''}',
                hint: 'qwen2-vl',
                onChanged: (value) => _set('llm_model', value),
              )
            : IltSelect(
                value: '${_draft['llm_model'] ?? ''}',
                options: [
                  for (final model in _llmModels) (model, model),
                ],
                onChanged: (value) => _set('llm_model', value),
              ),
      ),
      FieldRow(
        label: 'Ключ API',
        child: IltTextField(
          key: const Key('wizard-llm-api-key'),
          value: '${_draft['api_key'] ?? ''}',
          hint: state.hasApiKey
              ? 'ключ уже сохранён — оставьте пустым'
              : 'если сервер требует',
          obscure: true,
          onChanged: (value) => _set('api_key', value),
        ),
      ),
      const SizedBox(height: 8),
      Row(
        children: [
          FilledButton(
            key: const Key('wizard-llm-check'),
            onPressed: _checking ? null : _checkLlm,
            child: Text(_checking ? 'Проверка…' : 'Проверить'),
          ),
          const SizedBox(width: 12),
          if (_llmOk == true)
            Text(
              'Сервер отвечает · моделей: ${_llmModels.length}',
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: palette.textSuccess),
            ),
          if (_llmOk == false)
            Expanded(
              child: Text(
                _llmReason.isEmpty || _llmReason == 'empty'
                    ? 'Адрес пуст или сервер недоступен'
                    : 'Недоступен: $_llmReason',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: palette.textError),
              ),
            ),
        ],
      ),
    ]);
  }

  Widget _languagesStep(BuildContext context) => _card(context, [
        const SectionHeader(
          title: 'Языки',
          lead: 'Язык оригинала можно оставить автоопределению.',
        ),
        FieldRow(
          label: 'Откуда',
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
          label: 'Куда',
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
      ]);
}

String _formatBytes(int value) {
  if (value >= 1024 * 1024 * 1024) {
    return '${(value / (1024 * 1024 * 1024)).toStringAsFixed(2)} ГБ';
  }
  if (value >= 1024 * 1024) {
    return '${(value / (1024 * 1024)).toStringAsFixed(0)} МБ';
  }
  if (value >= 1024) return '${(value / 1024).toStringAsFixed(0)} КБ';
  return '$value Б';
}

/// Ожидаемое время загрузки (грубо, ~10 МБ/с): «<1 мин» или «~N мин».
String _formatEta(int bytes) {
  final seconds = bytes / (10 * 1024 * 1024);
  if (seconds < 60) return '<1 мин';
  return '~${(seconds / 60).ceil()} мин';
}
