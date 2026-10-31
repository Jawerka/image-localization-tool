"""Единый план глифов по фактическим контурам, без пересечения курсивных букв."""
from __future__ import annotations

import math
import cv2
import numpy as np
from PIL import Image, ImageDraw


def glyph_plan(text, font, stroke_width=0, spacing=0.0):
    """Позиции относительно начала строки; явный отрицательный интервал сохраняется."""
    boxes = [font.getbbox(ch, stroke_width=stroke_width) for ch in text]
    if not boxes:
        return []
    top = min(box[1] for box in boxes) - 2
    bottom = max(box[3] for box in boxes) + 2
    left_pad = max(4, -min(box[0] for box in boxes) + 4)
    width = max(1, math.ceil(sum(max(float(font.getlength(ch)), box[2] - box[0]) +
                                abs(spacing) + stroke_width * 2 + 8 for ch, box in zip(text, boxes))))
    occupied = np.zeros((max(1, bottom - top), width + left_pad + 16), np.uint8)
    x = 0.0
    result = []
    for ch, box in zip(text, boxes):
        if not ch.isspace():
            part = Image.new('L', (max(1, box[2] - box[0]), max(1, box[3] - box[1])))
            ImageDraw.Draw(part).text((-box[0], -box[1]), ch, font=font, fill=255, stroke_width=stroke_width)
            ink = np.asarray(part) > 127
            gap = max(1, round(getattr(font, 'size', 12) / 72))
            blocked = cv2.dilate(occupied, np.ones((gap * 2 + 1, gap * 2 + 1), np.uint8))
            while True:
                px, py = round(x) + box[0] + left_pad, box[1] - top
                end = px + ink.shape[1]
                if end > occupied.shape[1]:
                    occupied = np.pad(occupied, ((0, 0), (0, end - occupied.shape[1] + 64)))
                    blocked = np.pad(blocked, ((0, 0), (0, occupied.shape[1] - blocked.shape[1])))
                if spacing < 0 or not np.any(blocked[py:py + ink.shape[0], px:end] & ink):
                    break
                x += 1
            occupied[py:py + ink.shape[0], px:end] |= ink.astype(np.uint8)
        result.append((ch, x))
        x += float(font.getlength(ch)) + spacing
    return result


def glyph_mask(text, font, stroke_width=0, spacing=0.0, line_spacing=20):
    """Собрать alpha всех строк; внешняя обводка применяется к общему слою."""
    lines = []
    for line in text.split('\n'):
        plan = glyph_plan(line, font, stroke_width, spacing)
        boxes = [(x + font.getbbox(ch, stroke_width=stroke_width)[0],
                  font.getbbox(ch, stroke_width=stroke_width)[1],
                  x + font.getbbox(ch, stroke_width=stroke_width)[2],
                  font.getbbox(ch, stroke_width=stroke_width)[3]) for ch, x in plan if not ch.isspace()]
        if not boxes:
            lines.append(Image.new('L', (1, max(1, getattr(font, 'size', 12)))))
            continue
        left, top = math.floor(min(b[0] for b in boxes)), min(b[1] for b in boxes)
        right, bottom = math.ceil(max(b[2] for b in boxes)), max(b[3] for b in boxes)
        layer = Image.new('L', (max(1, right - left), max(1, bottom - top)))
        paint = ImageDraw.Draw(layer)
        for ch, x in plan:
            paint.text((x - left, -top), ch, font=font, fill=255, stroke_width=stroke_width)
        lines.append(layer)
    gap = max(0, round(line_spacing))
    result = Image.new('L', (max(line.width for line in lines), sum(line.height for line in lines) + gap * (len(lines) - 1)))
    y = 0
    for line in lines:
        result.paste(line, ((result.width - line.width) // 2, y))
        y += line.height + gap
    return result
