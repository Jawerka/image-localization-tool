import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/errors.dart';
import '../../state/shell_state.dart';
import '../theme.dart';
import '../widgets.dart';

/// Мастер первого запуска: тема, модели, LLM, языки.
class FirstRunScreen extends StatefulWidget {
  const FirstRunScreen({super.key, required this.state});

  final ShellState state;

  @override
  State<FirstRunScreen> createState() => _FirstRunScreenState();
}

class _FirstRunScreenState extends State<FirstRunScreen> {
  static const steps = ['Тема', 'Модели', 'Сервер LLM', 'Языки'];

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
    };
    unawaited(state.secondary.refreshModels());
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
    await state.workspace.completeFirstRun(_draft);
    state.dismissFirstRun();
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
      await state.workspace.updateSettings({
        'llm_base_url': base,
        'llm_model': '${_draft['llm_model'] ?? ''}',
      });
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
                        'настройка займёт минуту · всё можно изменить позже',
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
                      1 => _modelsStep(context),
                      2 => _llmStep(context),
                      _ => _languagesStep(context),
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

  Widget _modelsStep(BuildContext context) {
    final secondary = state.secondary;
    final palette = IltPalette.of(context);
    final theme = Theme.of(context);
    final titles = {
      'detector': 'Детектор текста (RT-DETR)',
      'lama': 'LaMa · очистка баллонов',
      'font': 'Шрифты · офлайн-вёрстка',
    };
    final missing = [
      for (final model in secondary.models)
        if (!model.present) model.kind,
    ];
    return _card(context, [
      const SectionHeader(
        title: 'Модели',
        lead: 'Без них не работает распознавание и очистка. '
            'Скачиваются в папку models рядом с программой.',
      ),
      for (final model in secondary.models)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(
            children: [
              SizedBox(
                width: 200,
                child: Text(
                  titles[model.kind] ?? model.kind,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: palette.textPrimary),
                ),
              ),
              Expanded(
                child: model.downloading
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(2),
                        child: LinearProgressIndicator(value: model.percent),
                      )
                    : Text(
                        model.error.isNotEmpty
                            ? 'ошибка'
                            : (model.present ? 'уже на диске' : 'не скачано'),
                        style: theme.textTheme.labelSmall,
                      ),
              ),
              const SizedBox(width: 8),
              if (!model.present && !model.downloading)
                OutlinedButton(
                  key: Key('wizard-download-${model.kind}'),
                  onPressed: () => secondary.startDownload(model.kind),
                  child: const Text('Скачать'),
                )
              else if (model.present)
                Icon(Icons.check, size: 14, color: palette.textSuccess),
            ],
          ),
        ),
      if (missing.isNotEmpty) ...[
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('wizard-download-missing'),
          onPressed: () {
            for (final kind in missing) {
              secondary.startDownload(kind);
            }
          },
          child: const Text('Скачать недостающие'),
        ),
        const SizedBox(height: 6),
      ],
      Text(
        'Можно закрыть окно — загрузка продолжится в фоне.',
        style: theme.textTheme.labelSmall,
      ),
    ]);
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
