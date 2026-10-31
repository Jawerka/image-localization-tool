import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../state/workspace_state.dart';

/// Горячие клавиши канваса (зеркало `web/js/keys.js` для просмотрщика).
///
/// Возвращает [KeyEventResult.handled] только для перехваченных клавиш, чтобы
/// не мешать полям ввода и модалкам.
KeyEventResult handleViewerShortcut(
  KeyEvent event, {
  required WorkspaceState workspace,
  required bool enabled,
}) {
  final viewer = workspace.viewer;
  // Keyup Space сбрасываем до guard'ов: иначе зажатие с последующим фокусом
  // в поле ввода (или открытым оверлеем) оставляет «Руку» залипшей.
  if (event is KeyUpEvent && event.logicalKey == LogicalKeyboardKey.space) {
    viewer.session.setSpaceDown(false);
  }
  if (!enabled) return KeyEventResult.ignored;
  if (_isTyping()) return KeyEventResult.ignored;

  final key = event.logicalKey;
  final keyboard = HardwareKeyboard.instance;
  final control = keyboard.isControlPressed;
  final shift = keyboard.isShiftPressed;
  final alt = keyboard.isAltPressed;
  final meta = keyboard.isMetaPressed;
  final down = event is KeyDownEvent || event is KeyRepeatEvent;

  // Ctrl+Enter — перевести страницу, Ctrl+Shift+Enter — перевести всё
  // (условия те же, что у кнопки «Перевести»: проект открыт, прогон не идёт).
  if (control &&
      !alt &&
      !meta &&
      (key == LogicalKeyboardKey.enter ||
          key == LogicalKeyboardKey.numpadEnter)) {
    if (down && workspace.hasProject && !workspace.busy) {
      if (shift) {
        if (workspace.pages.isNotEmpty) workspace.translate();
      } else {
        final active = workspace.activePage;
        if (active != null) workspace.translate(pageId: active.id);
      }
    }
    return KeyEventResult.handled;
  }

  if (viewer.document == null) return KeyEventResult.ignored;

  if (control && !alt && !meta) {
    if (key == LogicalKeyboardKey.digit0) {
      if (down) viewer.session.fit();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.digit1) {
      if (down) viewer.session.zoom100();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyZ && !shift) {
      if (down) viewer.undo();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyY && !shift) {
      if (down) viewer.redo();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyC && shift) {
      if (down) viewer.copyStyle();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyV && shift) {
      if (down) viewer.pasteStyle();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }
  if (meta) return KeyEventResult.ignored;

  if (key == LogicalKeyboardKey.space) {
    if (event is KeyDownEvent) viewer.session.setSpaceDown(true);
    if (event is KeyUpEvent) viewer.session.setSpaceDown(false);
    return KeyEventResult.handled;
  }
  if (!down) return KeyEventResult.ignored;

  final direction = _arrowDirection(key);
  if (direction != null) {
    if (alt) {
      viewer.nudgeSelectedRegion(direction, shift: shift, alt: true);
      return KeyEventResult.handled;
    }
    if (viewer.selectedRegionId != null) {
      viewer.nudgeSelectedRegion(direction, shift: shift);
      return KeyEventResult.handled;
    }
    if (!shift &&
        (key == LogicalKeyboardKey.arrowLeft ||
            key == LogicalKeyboardKey.arrowRight)) {
      workspace.stepPage(key == LogicalKeyboardKey.arrowRight ? 1 : -1);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  switch (key) {
    case LogicalKeyboardKey.keyV:
      viewer.setTool('select');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyR:
      viewer.setTool('region');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyB:
      viewer.setTool('brush');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyG:
      viewer.setTool('fill');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyP:
      viewer.setTool('polyline');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyH:
      viewer.setTool('hand');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyL:
      if (shift) return KeyEventResult.ignored;
      viewer.toggleBoxes();
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyM:
      if (shift) return KeyEventResult.ignored;
      viewer.toggleMask();
      return KeyEventResult.handled;
    case LogicalKeyboardKey.bracketLeft:
      viewer.nudgeBrush(-1);
      return KeyEventResult.handled;
    case LogicalKeyboardKey.bracketRight:
      viewer.nudgeBrush(1);
      return KeyEventResult.handled;
    case LogicalKeyboardKey.escape:
      if (viewer.session.cancelGesture()) {
        return KeyEventResult.handled;
      }
      if (viewer.session.lasso.isNotEmpty) {
        viewer.cancelLassoDraft();
        return KeyEventResult.handled;
      }
      if (viewer.session.strokePoints.isNotEmpty) {
        viewer.session.clearStroke();
        return KeyEventResult.handled;
      }
      if (viewer.selectedRegionId != null) {
        viewer.selectRegion(null);
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    case LogicalKeyboardKey.enter:
    case LogicalKeyboardKey.numpadEnter:
      return viewer.commitLassoDraft()
          ? KeyEventResult.handled
          : KeyEventResult.ignored;
    case LogicalKeyboardKey.delete:
      if (viewer.selectedRegionId == null) return KeyEventResult.ignored;
      viewer.deleteSelectedRegion();
      return KeyEventResult.handled;
    case LogicalKeyboardKey.pageUp:
      workspace.stepPage(-1);
      return KeyEventResult.handled;
    case LogicalKeyboardKey.pageDown:
      workspace.stepPage(1);
      return KeyEventResult.handled;
    case LogicalKeyboardKey.keyN:
      if (shift || alt) return KeyEventResult.ignored;
      workspace.focusNextProblem();
      return KeyEventResult.handled;
    case LogicalKeyboardKey.digit1:
      if (shift) return KeyEventResult.ignored;
      viewer.setView('original');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.digit2:
      if (shift) return KeyEventResult.ignored;
      viewer.setView('result');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.digit3:
      if (shift) return KeyEventResult.ignored;
      viewer.setView('compare');
      return KeyEventResult.handled;
    case LogicalKeyboardKey.digit4:
      if (shift) return KeyEventResult.ignored;
      viewer.setView('clean');
      return KeyEventResult.handled;
  }
  return KeyEventResult.ignored;
}

/// Направление стрелки или null.
String? _arrowDirection(LogicalKeyboardKey key) {
  if (key == LogicalKeyboardKey.arrowLeft) return 'left';
  if (key == LogicalKeyboardKey.arrowRight) return 'right';
  if (key == LogicalKeyboardKey.arrowUp) return 'up';
  if (key == LogicalKeyboardKey.arrowDown) return 'down';
  return null;
}

/// Фокус в текстовом поле — однобуквенные сокращения не работают.
bool _isTyping() {
  final focus = FocusManager.instance.primaryFocus;
  final context = focus?.context;
  if (context == null) return false;
  return context.findAncestorWidgetOfExactType<EditableText>() != null;
}
