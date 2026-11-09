"""Независимые повёрнутые и перспективные поля подтверждённых экземпляров строк."""
from __future__ import annotations

import math
import cv2
import numpy as np
from PIL import Image

from src.components.readable_reflow import readable_reflow


def _ordered(points):
    """Порядок TL, TR, BR, BL для преимущественно горизонтальной строки."""
    points = np.asarray(points, np.float32)
    by_x = points[np.argsort(points[:, 0])]
    left, right = by_x[:2], by_x[2:]
    left = left[np.argsort(left[:, 1])]
    right = right[np.argsort(right[:, 1])]
    return np.array([left[0], right[0], right[1], left[1]], np.float32)


def line_frame(ink, offset=(0, 0)):
    """Оценить геометрию одного экземпляра, не обещая разделения слитых строк."""
    binary = (np.asarray(ink) > 0).astype(np.uint8)
    ys, xs = np.where(binary)
    if len(xs) < 20:
        return None
    hull = cv2.convexHull(np.column_stack((xs, ys)).astype(np.float32))
    rect = cv2.minAreaRect(hull)
    if min(rect[1]) < 3:
        return None
    quad = _ordered(cv2.boxPoints(rect))
    kind = 'rbox'
    perimeter = cv2.arcLength(hull, True)
    candidate = cv2.approxPolyDP(hull, .025*perimeter, True)
    if len(candidate) == 4 and cv2.isContourConvex(candidate):
        candidate = _ordered(candidate.reshape(4, 2))
        area = abs(cv2.contourArea(candidate))
        rectangle_area = max(1., float(rect[1][0]*rect[1][1]))
        # Незначительное отличие не оправдывает дополнительные степени свободы.
        if .65 <= area/rectangle_area <= .92 and area >= len(xs)*.85:
            quad, kind = candidate, 'quad'
    width = float((np.linalg.norm(quad[1]-quad[0])+np.linalg.norm(quad[2]-quad[3]))/2)
    height = float((np.linalg.norm(quad[3]-quad[0])+np.linalg.norm(quad[2]-quad[1]))/2)
    if width < height*1.5:
        return None
    vector = (quad[1]-quad[0])+(quad[2]-quad[3])
    angle = -math.degrees(math.atan2(float(vector[1]), float(vector[0])))
    quad += np.asarray(offset, np.float32)
    return dict(kind=kind, quad=quad.tolist(), width=width, height=height, angle=angle,
                evidence='оболочка экземпляра; это не оценка уверенности OCR или числа строк')


def render_line_frame(text, font_path, font_size, frame, canvas_size, stroke_width=2):
    """Перенести полный растр в своё поле; при нехватке места не уменьшать кегль."""
    width, height = max(1, round(frame['width'])), max(1, round(frame['height']))
    if max(width, height, *canvas_size) > 8192:
        raise ValueError('Слишком большая область')
    layer, fitted = readable_reflow(text, font_path, font_size, np.ones((height, width), np.uint8), stroke_width)
    if layer is None:
        return None, fitted
    src = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
    matrix = cv2.getPerspectiveTransform(src, np.float32(frame['quad']))
    rgba = np.asarray(layer).astype(np.float32)/255
    # Предумноженная alpha предотвращает тёмный ореол ресэмплинга белой обводки.
    rgba[..., :3] *= rgba[..., 3:4]
    turned = cv2.warpPerspective(rgba, matrix, tuple(canvas_size), flags=cv2.INTER_CUBIC)
    turned = np.clip(turned, 0, 1)
    turned[..., :3] /= np.maximum(turned[..., 3:4], 1e-6)
    turned = np.clip(turned*255, 0, 255).astype(np.uint8)
    return Image.fromarray(turned), dict(fitted, geometry=frame['kind'], angle=frame['angle'])
