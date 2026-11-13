import 'dart:typed_data';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

/// Масштаб под указателем и перетаскивание рукой без панели инструментов.
class QuickImageView extends StatefulWidget {
  const QuickImageView({super.key, required this.pixels});

  final Uint8List pixels;

  @override
  State<QuickImageView> createState() => _QuickImageViewState();
}

class _QuickImageViewState extends State<QuickImageView> {
  final _transform = TransformationController();
  bool _dragging = false;

  @override
  void dispose() {
    _transform.dispose();
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
            ),
          ),
        ),
      ),
    ),
  );
}
