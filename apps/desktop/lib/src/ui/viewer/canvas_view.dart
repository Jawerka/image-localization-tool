import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

import '../../model/page_document.dart';
import '../../model/view_transform.dart';
import '../../state/viewer_state.dart';
import '../theme.dart';
import 'canvas_geometry.dart';
import 'canvas_painter.dart';

/// Канвас просмотрщика: лист, оверлеи и жест-машина инструментов.
///
/// Сцена намеренно без `RepaintBoundary` (см. `specs/023-viewer/spike.md`):
/// transform применяет `InteractiveViewer`, панорама перерисовывает пасс.
class CanvasView extends StatefulWidget {
  const CanvasView({super.key, required this.viewer});

  final ViewerState viewer;

  @override
  State<CanvasView> createState() => _CanvasViewState();
}

/// Живой жест.
class _Drag {
  _Drag(this.kind);

  final String kind; // pan | stroke | draft | curtain | move | resize | rotate | warp
  Offset lastLocal = Offset.zero;
  Offset startScene = Offset.zero;
  Rect startRect = Rect.zero;
  Rect bbox = Rect.zero;
  String handle = '';
  String regionId = '';
  String mode = Stroke.paint;
  int warpIndex = 0;
  double startAngle = 0;
  double startRotation = 0;
  bool moved = false;
}

class _CanvasViewState extends State<CanvasView> {
  final TransformationController _controller = TransformationController();
  _Drag? _drag;
  Duration? _lastTapTime;
  Offset? _lastTapLocal;
  Size _viewport = Size.zero;

  ViewerState get viewer => widget.viewer;
  CanvasSession get session => widget.viewer.session;

  @override
  void initState() {
    super.initState();
    session.addListener(_syncTransform);
    _syncTransform();
  }

  @override
  void dispose() {
    session.removeListener(_syncTransform);
    _controller.dispose();
    super.dispose();
  }

  static Matrix4 _toMatrix(ViewTransform transform) => Matrix4.identity()
    ..setEntry(0, 0, transform.scale)
    ..setEntry(1, 1, transform.scale)
    ..setEntry(0, 3, transform.tx)
    ..setEntry(1, 3, transform.ty);

  void _syncTransform() {
    if (!mounted) return;
    final next = _toMatrix(session.transform);
    if (_controller.value.storage[0] == next.storage[0] &&
        _controller.value.storage[5] == next.storage[5] &&
        _controller.value.storage[12] == next.storage[12] &&
        _controller.value.storage[13] == next.storage[13]) {
      return;
    }
    final phase = SchedulerBinding.instance.schedulerPhase;
    if (phase == SchedulerPhase.persistentCallbacks ||
        phase == SchedulerPhase.midFrameMicrotasks) {
      SchedulerBinding.instance.addPostFrameCallback((_) {
        if (mounted) _controller.value = next;
      });
    } else {
      _controller.value = next;
    }
  }

  // ---- жесты ---------------------------------------------------------------

  bool _isDoubleTap(PointerDownEvent event) {
    final lastTime = _lastTapTime;
    final lastLocal = _lastTapLocal;
    final isDouble = lastTime != null &&
        lastLocal != null &&
        event.timeStamp - lastTime < const Duration(milliseconds: 350) &&
        (event.localPosition - lastLocal).distance < 8;
    _lastTapTime = event.timeStamp;
    _lastTapLocal = event.localPosition;
    return isDouble;
  }

  void _onSignal(PointerSignalEvent event) {
    if (event is! PointerScrollEvent || viewer.document == null) return;
    if (HardwareKeyboard.instance.isControlPressed) {
      session.zoomStep(
        event.scrollDelta.dy < 0 ? 1 : -1,
        focal: event.localPosition,
      );
    } else {
      session.scrollBy(event.scrollDelta);
    }
  }

  void _onHover(PointerHoverEvent event) {
    if (viewer.tool == 'brush' && !session.spaceDown) {
      session.setCursor(event.localPosition);
    } else if (session.cursor != null) {
      session.setCursor(null);
    }
  }

  void _onPointerDown(PointerDownEvent event) {
    final document = viewer.document;
    if (document == null) return;
    final local = event.localPosition;
    final scene = session.transform.toScene(local);
    final middle = event.buttons & kMiddleMouseButton != 0;
    final secondary = event.buttons & kSecondaryMouseButton != 0;
    final primary = event.buttons & kPrimaryMouseButton != 0;

    if (middle || session.spaceDown || viewer.tool == 'hand') {
      _drag = _Drag('pan')..lastLocal = local;
      return;
    }
    switch (viewer.tool) {
      case 'brush':
        if (!primary && !secondary) return;
        final mode = secondary ? Stroke.erase : Stroke.paint;
        _drag = _Drag('stroke')..mode = mode;
        session.beginStroke(mode, scene);
        session.setCursor(local);
        return;
      case 'polyline':
        if (!primary && !secondary) return;
        if (_isDoubleTap(event)) {
          viewer.commitLassoDraft();
          return;
        }
        if (session.lasso.isEmpty) {
          session.lassoMode = secondary ? Stroke.eraseFill : Stroke.fill;
        }
        session.addLassoPoint(scene);
        session.setLassoHover(scene);
        return;
      case 'region':
        if (!primary) return;
        _drag = _Drag('draft')..startScene = scene;
        session.setDraftRect(Rect.fromPoints(scene, scene));
        return;
    }
    if (secondary) return;
    _selectDown(event, scene);
  }

  void _selectDown(PointerDownEvent event, Offset scene) {
    final document = viewer.document!;
    final scale = session.transform.scale;
    final selected = document.findRegion(viewer.selectedRegionId);
    if (selected != null) {
      final previewPoints = session.previewWarpId == selected.id
          ? session.previewWarpPoints
          : null;
      final points = previewPoints ?? warpPointsFor(selected);
      for (var index = 0; index < points.length; index++) {
        if ((scene - points[index]).distance <= 8 / scale) {
          if (_isDoubleTap(event)) {
            viewer.resetWarpPoint(selected.id, index);
            return;
          }
          _drag = _Drag('warp')
            ..regionId = selected.id
            ..warpIndex = index
            ..bbox = selected.bbox;
          session.setPreviewWarp(selected.id, [...points]);
          return;
        }
      }
      if (hitRotateHandle(selected.bbox, scene, scale)) {
        _drag = _Drag('rotate')
          ..regionId = selected.id
          ..bbox = selected.bbox
          ..startAngle = pointerAngle(scene, selected.bbox)
          ..startRotation = selected.rotation;
        return;
      }
    }
    final hit = viewer.showBoxes
        ? hitTestRegion(
            regions: document.regions,
            scenePoint: scene,
            transform: session.transform,
            selectedId: viewer.selectedRegionId,
          )
        : null;
    if (hit != null) {
      viewer.selectRegion(hit.region.id);
      _drag = _Drag(hit.handle.isEmpty ? 'move' : 'resize')
        ..regionId = hit.region.id
        ..handle = hit.handle
        ..startScene = scene
        ..startRect = hit.region.bbox
        ..bbox = hit.region.bbox;
      session.setPreviewRect(hit.region.id, hit.region.bbox);
      return;
    }
    if (viewer.view == 'compare') {
      _drag = _Drag('curtain')..lastLocal = event.localPosition;
      return;
    }
    viewer.selectRegion(null);
  }

  void _onPointerMove(PointerMoveEvent event) {
    final drag = _drag;
    if (drag == null) return;
    final local = event.localPosition;
    final scene = session.transform.toScene(local);
    switch (drag.kind) {
      case 'pan':
        session.panBy(local - drag.lastLocal);
        drag.lastLocal = local;
      case 'stroke':
        session.addStrokePoint(scene);
        session.setCursor(local);
      case 'draft':
        session.setDraftRect(Rect.fromPoints(drag.startScene, scene));
        drag.moved = true;
      case 'curtain':
        drag.moved = true;
        _setCurtain(local);
      case 'move':
      case 'resize':
        final next = clampBox(
          applyHandleDrag(
            handle: drag.handle,
            start: drag.startRect,
            delta: scene - drag.startScene,
          ),
          viewer.imageSize.width,
          viewer.imageSize.height,
        );
        drag.moved = true;
        session.setPreviewRect(drag.regionId, next);
      case 'rotate':
        final angle = drag.startRotation +
            (pointerAngle(scene, drag.bbox) - drag.startAngle);
        drag.moved = true;
        session.setPreviewRotation(drag.regionId, angle);
      case 'warp':
        final points = session.previewWarpPoints;
        if (points == null || drag.warpIndex >= points.length) return;
        final next = [...points];
        next[drag.warpIndex] = scene;
        if (HardwareKeyboard.instance.isShiftPressed) {
          final region = viewer.document?.findRegion(drag.regionId);
          final mesh =
              region?.warp?['kind'] == 'mesh';
          final opposite = warpOppositeIndex(drag.warpIndex, mesh: mesh);
          if (opposite < next.length) {
            final localPoint = scene - drag.bbox.topLeft;
            next[opposite] = drag.bbox.bottomRight -
                Offset(localPoint.dx, localPoint.dy);
          }
        }
        drag.moved = true;
        session.setPreviewWarp(drag.regionId, next);
    }
  }

  void _onPointerUp(PointerEvent event) {
    final drag = _drag;
    _drag = null;
    if (drag == null) return;
    switch (drag.kind) {
      case 'stroke':
        _commitStroke();
      case 'draft':
        final rect = session.draftRect;
        session.setDraftRect(null);
        if (rect != null && rect.width >= 4 && rect.height >= 4) {
          viewer.createRegion(rect);
        }
      case 'move':
      case 'resize':
        if (drag.moved) {
          final rect = session.previewRect;
          if (rect != null) viewer.commitRegionRect(drag.regionId, rect);
        }
        session.clearPreviews();
      case 'rotate':
        final angle = session.previewRotation;
        if (drag.moved && angle != null) {
          viewer.commitRegionRotation(drag.regionId, angle);
        }
        session.clearPreviews();
      case 'warp':
        final points = session.previewWarpPoints;
        if (drag.moved && points != null) {
          viewer.commitWarpPoints(drag.regionId, points);
        }
        session.clearPreviews();
      case 'curtain':
        if (!drag.moved) viewer.selectRegion(null);
      case 'pan':
        break;
    }
  }

  void _setCurtain(Offset local) {
    final transform = session.transform;
    final width = viewer.imageSize.width * transform.scale;
    if (width <= 0) return;
    viewer.setCurtain((local.dx - transform.tx) / width);
  }

  void _commitStroke() {
    final points = session.strokePoints;
    if (points.isEmpty) return;
    final mode = session.strokeMode;
    final radius = viewer.brushSize;
    viewer.editDocument(
      (document) => document.addStroke(
        Stroke(
          mode: mode,
          radius: radius,
          points: [
            for (final point in points)
              Offset(point.dx.roundToDouble(), point.dy.roundToDouble()),
          ],
        ),
      ),
      deferApply: true,
    );
    session.clearStroke();
  }

  MouseCursor _cursor() {
    if (session.spaceDown || viewer.tool == 'hand') {
      return SystemMouseCursors.grab;
    }
    switch (viewer.tool) {
      case 'brush':
        return SystemMouseCursors.precise;
      case 'region':
      case 'polyline':
        return SystemMouseCursors.precise;
      default:
        return SystemMouseCursors.basic;
    }
  }

  @override
  Widget build(BuildContext context) {
    final palette = IltPalette.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final viewport = constraints.biggest;
        if (viewport != _viewport) {
          _viewport = viewport;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) session.setViewport(viewport);
          });
        }
        final imageSize = viewer.imageSize;
        final sceneSize = imageSize.isEmpty ? viewport : imageSize;
        return Listener(
          behavior: HitTestBehavior.opaque,
          onPointerSignal: _onSignal,
          onPointerDown: _onPointerDown,
          onPointerMove: _onPointerMove,
          onPointerUp: _onPointerUp,
          onPointerCancel: _onPointerUp,
          onPointerHover: _onHover,
          child: ClipRect(
            // MouseRegion внутри AnimatedBuilder: курсор («Рука» по Space)
            // перерисовывается от уведомлений сессии, как и состав Stack.
            child: AnimatedBuilder(
              animation: Listenable.merge([viewer, session]),
              builder: (context, _) {
                // Размер листа сообщаем после кадра: setImageSize уведомляет
                // сессию, а уведомлять во время build нельзя.
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (!mounted) return;
                  viewer.noteDisplayedImage(
                    viewer.imageFor(
                      viewer.view == 'original' ? 'original' : 'result',
                    ),
                  );
                  session.setImageSize(viewer.imageSize);
                });
                return MouseRegion(
                  cursor: _cursor(),
                  onExit: (_) => session.setCursor(null),
                  child: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      Positioned.fill(
                        child: InteractiveViewer(
                          transformationController: _controller,
                          constrained: false,
                          panEnabled: false,
                          scaleEnabled: false,
                          minScale: ViewTransform.minScale,
                          maxScale: ViewTransform.maxScale,
                          boundaryMargin:
                              const EdgeInsets.all(double.infinity),
                          child: SizedBox(
                            width: sceneSize.width,
                            height: sceneSize.height,
                            child: CustomPaint(
                              painter: ScenePainter(
                                viewer: viewer,
                                session: session,
                                palette: palette,
                              ),
                            ),
                          ),
                        ),
                      ),
                      if (viewer.tool == 'brush' && !session.spaceDown)
                        _BrushCursor(
                          key: const Key('viewer-brush-cursor'),
                          viewer: viewer,
                          session: session,
                        ),
                    ],
                  ),
                );
              },
            ),
          ),
        );
      },
    );
  }
}

/// Экранный кружок кисти: диаметр = 2×толщина×масштаб.
class _BrushCursor extends StatelessWidget {
  const _BrushCursor({super.key, required this.viewer, required this.session});

  final ViewerState viewer;
  final CanvasSession session;

  @override
  Widget build(BuildContext context) {
    final cursor = session.cursor;
    if (cursor == null) return const SizedBox.shrink();
    final diameter =
        math.max(4.0, viewer.brushSize * 2 * session.transform.scale);
    return Positioned(
      left: cursor.dx - diameter / 2,
      top: cursor.dy - diameter / 2,
      width: diameter,
      height: diameter,
      child: IgnorePointer(
        child: DecoratedBox(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: const Color(0xCCFFFFFF), width: 1.5),
            boxShadow: const [
              BoxShadow(color: Color(0x66000000), blurRadius: 2),
            ],
          ),
        ),
      ),
    );
  }
}
