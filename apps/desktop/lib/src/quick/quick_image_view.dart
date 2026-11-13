import 'dart:typed_data';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

/// Масштаб под указателем и перетаскивание рукой без панели инструментов.
class QuickImageView extends StatefulWidget {
  const QuickImageView({
    super.key,
    required this.pixels,
    this.onFirstFrame,
    this.transformationController,
  });

  final Uint8List pixels;
  final VoidCallback? onFirstFrame;
  final TransformationController? transformationController;

  @override
  State<QuickImageView> createState() => _QuickImageViewState();
}

class _QuickImageViewState extends State<QuickImageView> {
  late final _transform =
      widget.transformationController ?? TransformationController();
  bool _dragging = false;
  bool _reported = false;

  @override
  void dispose() {
    if (widget.transformationController == null) _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MouseRegion(
    cursor: _dragging ? SystemMouseCursors.grabbing : SystemMouseCursors.grab,
    child: Listener(
      onPointerDown: (event) {
        if (event.buttons == kPrimaryMouseButton) {
          setState(() => _dragging = true);
        }
      },
      onPointerUp: (_) => setState(() => _dragging = false),
      onPointerCancel: (_) => setState(() => _dragging = false),
      child: GestureDetector(
        onDoubleTap: () => _transform.value = Matrix4.identity(),
        child: InteractiveViewer(
          transformationController: _transform,
          minScale: 1,
          maxScale: 16,
          child: SizedBox.expand(
            child: Image.memory(
              widget.pixels,
              fit: BoxFit.contain,
              gaplessPlayback: true,
              errorBuilder: (_, _, _) => const SizedBox.shrink(),
              frameBuilder: (context, child, frame, synchronous) {
                if (frame != null && !_reported) {
                  _reported = true;
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    if (mounted) widget.onFirstFrame?.call();
                  });
                }
                return child;
              },
            ),
          ),
        ),
      ),
    ),
  );
}
