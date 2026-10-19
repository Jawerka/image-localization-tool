import 'package:flutter/material.dart';

import '../state/workspace_state.dart';
import 'theme.dart';

/// Подписи этапов — точь-в-точь как `STAGE_LABELS` в `web/js/state.js`.
const Map<String, String> stageLabels = {
  'detect': 'Детекция',
  'detection': 'Детекция',
  'ocr': 'OCR',
  'translate': 'Перевод',
  'translation': 'Перевод',
  'segment': 'Сегмент',
  'mask': 'Маска',
  'inpaint': 'Очистка',
  'clean': 'Очистка',
  'typeset': 'Вёрстка',
  'export-wait': 'Ожидание результата',
};

String stageLabel(String stage) {
  if (stage.isEmpty) return '';
  return stageLabels[stage.toLowerCase()] ?? stage;
}

/// Текст статуса страницы — как `statusText` в `web/js/state.js`.
String pageStatusText(PageRow page) {
  switch (page.status) {
    case 'queued':
      return 'в очереди';
    case 'running':
      final progress =
          page.progress < 0 ? 0 : (page.progress > 100 ? 100 : page.progress);
      final stage = stageLabel(page.stage);
      return stage.isEmpty ? 'идёт $progress %' : 'идёт $progress % · $stage';
    case 'done':
      return 'готово';
    case 'edited':
      return 'есть правки';
    case 'offline':
      return 'без LLM';
    case 'error':
      return 'ошибка';
    default:
      return 'не начата';
  }
}

/// Цвет точки/акцента по нормализованному статусу.
Color statusColor(IltPalette palette, String status) {
  switch (status) {
    case 'done':
    case 'edited':
      return palette.textSuccess;
    case 'offline':
      return palette.textWarning;
    case 'error':
      return palette.textError;
    case 'running':
      return palette.primaryHover;
    case 'queued':
      return palette.textMuted;
    default:
      return palette.borderStrong;
  }
}

/// Иконка статуса страницы (соответствует ICONS в web).
IconData statusIcon(String status) {
  switch (status) {
    case 'queued':
      return Icons.schedule;
    case 'running':
      return Icons.play_arrow;
    case 'done':
      return Icons.check;
    case 'edited':
      return Icons.brush;
    case 'offline':
      return Icons.warning_amber;
    case 'error':
      return Icons.error_outline;
    default:
      return Icons.description_outlined;
  }
}
