"""Разбиение реплики по реальной ширине строк внутри облачка."""

import math
from functools import cache

import numpy as np


def separate_neighbour_bubbles(mask, region, regions):
    """Разделить пересекающиеся облачка по зазору исходных текстовых рамок."""
    if region.document or region.bubble_bbox is None or region.block_type == "sfx":
        return mask
    result = mask.copy()
    bx, by, bw, bh = region.bubble_bbox
    x, y, w, h = region.bbox
    for other in regions:
        if other.id == region.id or other.document or other.bubble_bbox is None or other.block_type == "sfx" or other.skip or not other.translation.strip():
            continue
        ox, oy, ow, oh = other.bubble_bbox
        if min(bx+bw, ox+ow) <= max(bx, ox) or min(by+bh, oy+oh) <= max(by, oy):
            continue
        tx, ty, tw, th = other.bbox
        # Разделяем только подтверждённый зазор, не режем пересекающийся исходный текст.
        if x+w <= tx:
            cut = max(0, min(result.shape[1], (x+w+tx)//2))
            result[:, cut:] = 0
        elif tx+tw <= x:
            cut = max(0, min(result.shape[1], (tx+tw+x)//2))
            result[:, :cut] = 0
        elif y+h <= ty:
            cut = max(0, min(result.shape[0], (y+h+ty)//2))
            result[cut:, :] = 0
        elif ty+th <= y:
            cut = max(0, min(result.shape[0], (ty+th+y)//2))
            result[:cut, :] = 0
    return result


def shape_row_spans(mask):
    """Брать непрерывную полосу, не соединяя пустоту между хвостами облачка."""
    spans = []
    for row in mask:
        xs = np.flatnonzero(row)
        if not len(xs):
            spans.append(None)
            continue
        groups = np.split(xs, np.flatnonzero(np.diff(xs) > 1) + 1)
        run = max(groups, key=len)
        spans.append((int(run[0]), int(run[-1])))
    return spans


def layout_in_shape(
    text,
    font,
    draw,
    spans,
    hyphenator,
    align,
    strict=True,
    letter_spacing=0.0,
    line_spacing=0.0,
    stroke_pad=0,
):
    """Искать полное разбиение слов; координаты учитывают вынос глифов."""
    words = text.split()
    if not words:
        return [], True
    rows = [y for y, span in enumerate(spans) if span is not None]
    if not rows:
        return [], False
    size = getattr(font, "size", 12)
    glyph = font.getbbox("ЙАygрд" + "".join(words))
    ink_h = glyph[3] - glyph[1]
    pad = max(0, int(stroke_pad)) + max(2, round(size * 0.15))
    line_h = max(1, round(max(size, ink_h * 1.15) + line_spacing))
    top, bottom = rows[0], rows[-1] + 1

    @cache
    def bounds(line):
        if letter_spacing:
            width = sum(float(draw.textlength(ch, font=font)) for ch in line)
            width += max(0, len(line) - 1) * letter_spacing
            # Запас под крайние выносы курсивных глифов.
            box = font.getbbox(line)
            return min(0, box[0]), max(math.ceil(width), box[2])
        box = font.getbbox(line)
        return box[0], max(box[2], math.ceil(draw.textlength(line, font=font)))

    max_width = (
        max(right - left + 1 for left, right in (spans[y] for y in rows)) - 2 * pad
    )
    # Переносить длинное слово только когда оно не помещается даже в широкой строке.
    tokens = []
    for word in words:
        while hyphenator and bounds(word)[1] - bounds(word)[0] > max_width:
            cuts = [
                p for p in hyphenator.positions(word) if p >= 3 and len(word) - p >= 3
            ]
            cuts = [
                p
                for p in cuts
                if bounds(word[:p] + "-")[1] - bounds(word[:p] + "-")[0] <= max_width
            ]
            if not cuts:
                break
            cut = max(cuts)
            tokens.append(word[:cut] + "-")
            word = word[cut:]
        tokens.append(word)
    words = tokens
    max_lines = min(
        len(words), 80, (bottom - top - 2 * pad + max(0, line_h - ink_h)) // line_h
    )
    # Не измерять все сочетания строк для заведомо слишком крупного кегля.
    word_widths = [bounds(word)[1] - bounds(word)[0] for word in words]
    if max_lines <= 0 or max(word_widths) > max_width:
        return [], False
    if sum(word_widths) > max_lines * max_width:
        return [], False
    best = None
    for count in range(1, max_lines + 1):
        block_h = (count - 1) * line_h + ink_h + 2 * pad
        if block_h > bottom - top:
            continue
        center_y = (top + bottom - block_h) // 2
        for shift in (0, -line_h // 3, line_h // 3):
            start = center_y + shift
            bands = []
            for i in range(count):
                y = start + i * line_h
                if y < top or y + ink_h + 2 * pad > bottom:
                    break
                stripe = spans[y : y + ink_h + 2 * pad]
                if any(s is None for s in stripe):
                    break
                left = max(s[0] for s in stripe) + pad
                right = min(s[1] for s in stripe) - pad
                if right - left < 1:
                    break
                bands.append((left, right, y + pad))
            if len(bands) != count:
                continue

            @cache
            def solve(row, index, count=count, bands=tuple(bands)):
                if row == count:
                    return (0.0, ()) if index == len(words) else None
                left, right, _ = bands[row]
                available = right - left + 1
                winner = None
                for end in range(index + 1, len(words) - (count - row - 1) + 1):
                    line = " ".join(words[index:end])
                    a, b = bounds(line)
                    width = b - a
                    if width > available:
                        break
                    tail = solve(row + 1, end)
                    if tail is None:
                        continue
                    cost = ((available - width) / max(1, available)) ** 2 + tail[0]
                    value = (cost, (line,) + tail[1])
                    if winner is None or cost < winner[0]:
                        winner = value
                return winner

            solution = solve(0, 0)
            solve.cache_clear()
            if solution is None:
                continue
            cost = solution[0] / count + abs(shift) / max(1, bottom - top) * 0.1
            if best is None or cost < best[0]:
                placed = []
                for line, (left, right, y) in zip(solution[1], bands):
                    a, b = bounds(line)
                    width = b - a
                    x = (
                        left
                        if align == "left"
                        else (
                            right - width + 1
                            if align == "right"
                            else (left + right - width + 1) // 2
                        )
                    )
                    # Pillow по умолчанию рисует ниже y на величину верхнего выноса.
                    placed.append((line, int(x - a), int(y - glyph[1])))
                best = (cost, placed)
    return (best[1], True) if best else ([], False)
