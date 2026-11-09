"""Разбиение реплики по реальной ширине строк внутри облачка."""

import math
from functools import cache

import numpy as np
import cv2


def covers_source(mask, region, minimum=.75):
    """Отсечь контур одной строки, ошибочно принятый за всё облачко."""
    x, y, w, h = region.bbox
    patch = mask[max(0, y):min(mask.shape[0], y + h), max(0, x):min(mask.shape[1], x + w)]
    if not patch.size:
        return False
    ys, xs = np.nonzero(patch)
    if not len(xs) or xs.max() - xs.min() + 1 < patch.shape[1] * .75 or ys.max() - ys.min() + 1 < patch.shape[0] * .75:
        return False
    # У наклонной реплики пустые углы AABB не являются местом для букв.
    angle = abs(float(region.style.rotation or 0))
    threshold = minimum * max(.2, 1 - .025 * min(angle, 35))
    return bool(np.mean(patch > 0) >= threshold)


def light_layout_area(image, region, fallback):
    """Светлое тело облачка: залить буквенные дыры только для вёрстки."""
    if region.bubble_bbox is None:
        return fallback
    bx, by, bw, bh = region.bubble_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(image.shape[1], bx + bw), min(image.shape[0], by + bh)
    if x1 <= x0 or y1 <= y0:
        return fallback
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    tx, ty, tw, th = region.bbox
    xa, ya = max(0, tx - x0), max(0, ty - y0)
    xb, yb = min(gray.shape[1], tx + tw - x0), min(gray.shape[0], ty + th - y0)
    patch = gray[ya:yb, xa:xb]
    if not patch.size or np.percentile(patch, 75) < 160:
        return fallback
    threshold = max(145, min(225, float(np.percentile(patch, 75)) - 28))
    _, labels, stats, _ = cv2.connectedComponentsWithStats((gray >= threshold).astype(np.uint8))
    hits = np.bincount(labels[ya:yb, xa:xb].ravel(), minlength=len(stats))
    hits[0] = 0
    label = int(np.argmax(hits))
    if not label or stats[label, cv2.CC_STAT_AREA] > gray.size * .94:
        return fallback
    local = (labels == label).astype(np.uint8) * 255
    contours, _ = cv2.findContours(local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(local, contours, -1, 255, -1)
    result = np.zeros_like(fallback)
    result[y0:y1, x0:x1] = local
    if not covers_source(result, region, .85):
        return fallback
    if covers_source(fallback, region) and np.count_nonzero(result) <= np.count_nonzero(fallback) * 1.08:
        return fallback
    return result


def balloon_body(mask, region):
    """Убрать тонкие хвосты, сохранив широкое тело и исходную реплику."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return mask
    radius = max(1, round(min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) * .08))
    local = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    body = cv2.morphologyEx(local, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)))
    result = np.zeros_like(mask)
    result[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = body
    if np.count_nonzero(body) < len(xs) * .65 or not covers_source(result, region, .65):
        return mask
    return result


def bbox_ellipse_layout_area(region, fallback):
    """Вписанный в ``bubble_bbox`` эллипс только для вёрстки, не для ретуши."""
    if region.bubble_bbox is None:
        return fallback
    bx, by, bw, bh = (int(v) for v in region.bubble_bbox)
    if bw < 4 or bh < 4:
        return fallback
    result = np.zeros_like(fallback)
    cx = bx + bw / 2.0
    cy = by + bh / 2.0
    axes = (max(1, bw // 2), max(1, bh // 2))
    cv2.ellipse(result, (int(round(cx)), int(round(cy))), axes, 0, 0, 360, 255, -1)
    if not covers_source(result, region):
        return fallback
    if covers_source(fallback, region) and np.count_nonzero(result) <= np.count_nonzero(fallback) * 1.08:
        return fallback
    return result


def colour_layout_area(image, region, fallback):
    """Уточнить цветной полупрозрачный баллон без изменения маски ретуши."""
    from src.components.bubble_contour import balloon_seed

    seed = balloon_seed(image, region)
    if seed is None:
        return fallback
    sx, sy, _ = seed
    bx, by, bw, bh = region.bubble_bbox
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(image.shape[1], bx + bw), min(image.shape[0], by + bh)
    if not (x0 <= sx < x1 and y0 <= sy < y1):
        return fallback
    crop = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_RGB2HSV)
    hue, saturation, _ = (int(v) for v in crop[sy - y0, sx - x0])
    if saturation < 45:
        return fallback
    delta = np.abs(crop[..., 0].astype(int) - hue)
    delta = np.minimum(delta, 180 - delta)
    candidate = ((delta <= 12) & (crop[..., 1] >= max(30, saturation * .45)) &
                 (crop[..., 2] >= 60)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(candidate)
    label = labels[sy - y0, sx - x0]
    if not label or stats[label, cv2.CC_STAT_AREA] < bw * bh * .35:
        return fallback
    local = (labels == label).astype(np.uint8) * 255
    # Большая полоса на границе бокса означает утечку в рисунок.
    if any(np.mean(edge > 0) > .35 for edge in (local[0], local[-1], local[:, 0], local[:, -1])):
        return fallback
    contours, _ = cv2.findContours(local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(local, contours, -1, 255, -1)
    result = np.zeros_like(fallback)
    result[y0:y1, x0:x1] = local
    tx, ty, tw, th = region.bbox
    text = result[max(0, ty):ty + th, max(0, tx):tx + tw]
    if not text.size or np.mean(text > 0) < .85:
        return fallback
    # Не подменяем уже полную форму менее надёжной цветовой оценкой.
    if np.count_nonzero(result) <= np.count_nonzero(fallback) * 1.08:
        return fallback
    return result


def _region_centroid(region):
    x, y, w, h = region.bbox
    return x + w / 2.0, y + h / 2.0


def _neighbour_hit_mask(shape, other):
    """AABB раскладки соседа: облачко, иначе текстовый бокс (inferred)."""
    hit = np.zeros(shape[:2], np.uint8)
    geometry = other.auto_layout or {}
    box = geometry.get('ink_bbox', other.bbox) if geometry.get('readable_caption') else other.bubble_bbox or other.bbox
    x, y, w, h = (int(v) for v in box)
    y0, y1 = max(0, y), min(hit.shape[0], y + h)
    x0, x1 = max(0, x), min(hit.shape[1], x + w)
    if y1 > y0 and x1 > x0:
        hit[y0:y1, x0:x1] = 255
    return hit


def _keep_overlap_by_centroid(mask, region, other, overlap):
    """Оставить overlap-пиксели ближайшему из двух центроидов (ось лево/право или верх/низ)."""
    if not np.any(overlap):
        return mask
    cx, cy = _region_centroid(region)
    ox, oy = _region_centroid(other)
    ys, xs = np.nonzero(overlap)
    if abs(cx - ox) >= abs(cy - oy):
        own, neighbour = np.abs(xs - cx), np.abs(xs - ox)
    else:
        own, neighbour = np.abs(ys - cy), np.abs(ys - oy)
    keep = own < neighbour
    keep |= (own == neighbour) & (region.id < other.id)
    drop_y, drop_x = ys[~keep], xs[~keep]
    mask[drop_y, drop_x] = 0
    return mask


def separate_neighbour_bubbles(mask, region, regions):
    """Разделить пересекающиеся облачка по зазору рамок или по центроиду overlap."""
    if region.document or region.block_type == "sfx":
        return mask
    result = mask.copy()
    x, y, w, h = region.bbox
    own_box = ((region.auto_layout or {}).get('ink_bbox')
               if (region.auto_layout or {}).get('readable_caption') else region.bubble_bbox)
    for other in regions:
        if other.id == region.id or other.document or other.block_type == "sfx" or other.skip or not other.translation.strip():
            continue
        other_box = ((other.auto_layout or {}).get('ink_bbox')
                     if (other.auto_layout or {}).get('readable_caption') else other.bubble_bbox)
        if own_box is not None and other_box is not None:
            bx, by, bw, bh = own_box
            ox, oy, ow, oh = other_box
            if min(bx + bw, ox + ow) > max(bx, ox) and min(by + bh, oy + oh) > max(by, oy):
                tx, ty, tw, th = other.bbox
                # Разделяем только подтверждённый зазор, не режем пересекающийся исходный текст.
                if x + w <= tx:
                    cut = max(0, min(result.shape[1], (x + w + tx) // 2))
                    result[:, cut:] = 0
                elif tx + tw <= x:
                    cut = max(0, min(result.shape[1], (tx + tw + x) // 2))
                    result[:, :cut] = 0
                elif y + h <= ty:
                    cut = max(0, min(result.shape[0], (y + h + ty) // 2))
                    result[cut:, :] = 0
                elif ty + th <= y:
                    cut = max(0, min(result.shape[0], (ty + th + y) // 2))
                    result[:cut, :] = 0
        neighbour = _neighbour_hit_mask(result.shape, other)
        overlap = (result > 0) & (neighbour > 0)
        result = _keep_overlap_by_centroid(result, region, other, overlap)
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
    widest = max(spans[y][1] - spans[y][0] + 1 for y in rows)
    broad = [y for y in rows if spans[y][1] - spans[y][0] + 1 >= widest * .8]
    center_x = float(np.median([(spans[y][0] + spans[y][1]) / 2 for y in broad]))

    @cache
    def bounds(line):
        if letter_spacing:
            extra = (len(line) - 1) * letter_spacing
            width = sum(float(draw.textlength(ch, font=font)) for ch in line) + extra
            # Запас под крайние выносы курсивных глифов; отрицательный трекинг сужает и bbox.
            box = font.getbbox(line)
            return min(0, box[0]), max(math.ceil(width), box[2] + extra)
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
        # Длинный узкий хвост или вырез соседнего баллона смещает центр
        # всей высоты. Проверяем также центр широкого тела, не меняя форму.
        body_shift = round(float(np.median(broad)) - block_h / 2) - center_y
        for shift in dict.fromkeys((0, -line_h // 3, line_h // 3, body_shift)):
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
                            else max(left, min(right - width + 1, round(center_x - width / 2)))
                        )
                    )
                    # Pillow по умолчанию рисует ниже y на величину верхнего выноса.
                    placed.append((line, int(x - a), int(y - glyph[1])))
                best = (cost, placed)
    return (best[1], True) if best else ([], False)


def fallback_light_core(image, region):
    """Белое ядро открытой вспышки вместо прямоугольника поверх её лучей.

    Применяется лишь после провала обычного силуэта и flood. Отдельные
    буквенные дыры заполняются до открытия, тонкие лучи исключаются.
    """
    if region.bubble_bbox is None:
        return None
    bx,by,bw,bh=region.bubble_bbox
    x0,y0=max(0,bx),max(0,by)
    x1,y1=min(image.shape[1],bx+bw),min(image.shape[0],by+bh)
    if x1-x0<8 or y1-y0<8:
        return None
    gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY)
    count,labels,stats,_=cv2.connectedComponentsWithStats((gray>225).astype(np.uint8))
    if count<2:
        return None
    idx=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))
    if stats[idx,cv2.CC_STAT_AREA] < gray.size*.35:
        return None
    local=(labels==idx).astype(np.uint8)*255
    contours,_=cv2.findContours(local,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(local,contours,-1,255,-1)
    radius=max(2,round(min(gray.shape)*.09))
    local=cv2.morphologyEx(local,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))
    local=cv2.erode(local,np.ones((5,5),np.uint8))
    tx,ty,tw,th=region.bbox
    cx,cy=round(tx+tw/2-x0),round(ty+th/2-y0)
    if not (0<=cx<local.shape[1] and 0<=cy<local.shape[0] and local[cy,cx]):
        return None
    if np.count_nonzero(local)<gray.size*.3:
        return None
    result=np.zeros(image.shape[:2],np.uint8)
    result[y0:y1,x0:x1]=local
    return result
