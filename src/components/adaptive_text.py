"""Геометрия исходных надписей для общей очистки и вёрстки."""

from __future__ import annotations

import copy
import math
import cv2
import numpy as np
from PIL import Image

from src.components.sfx_ink import outline_pad_px
from src.components.retouch_ink import boundary_ink, confirmed_light_ink, smooth_line_mask
from src.components.text_segmenter import _outlined_text_mask, segment_regions


def is_balloon(region):
    """Роль речи важна и при отсутствии привязанного бокса облачка."""
    return (not region.document and region.block_type != 'sfx' and
            (region.bubble_bbox is not None or region.block_type == 'dialogue' or
             (region.class_name == 'text_bubble' and not region.block_type)))


def prepare_regions(image, regions, pixel_scale=1.0):
    """Запомнить геометрию до очистки, не изменяя ручные и уже подготовленные регионы."""
    white_components = None
    for region in regions:
        style = region.style
        if (region.auto_layout or region.manual or region.edited or region.layout_snapshot or region.document or
                style.rotation or style.skew_x or (style.warp or {}).get('kind', 'none') != 'none' or
                region.text_position is not None or region.block_type in ('title', 'sign', 'noise')):
            continue
        crop, ink, box = source_ink(image, region)
        ys, xs = np.where(ink > 0)
        if not len(xs):
            continue
        angle, evidence = text_angle(ink)
        bubble = is_balloon(region)
        if (region.bubble_bbox is None and abs(angle) >= 3 and
                getattr(region, '_retouch_preserve_background', False)):
            bubble = False
        if bubble and (sum(ch.isalnum() for ch in region.text) < 4 or
                       (any('\u3040' <= ch <= '\u9fff' for ch in region.text) and region.bbox[3] > region.bbox[2] * 1.2)):
            angle = 0.
            evidence = {'reason': 'короткий знак или вертикальная японская строка'}
        a, b, _, _ = box
        pad = 8. * pixel_scale
        if getattr(region, "_outline_ink", False):
            pad = outline_pad_px(ink, pixel_scale)
        geometry = dict(version=1, kind='bubble' if bubble else 'free', angle=angle, evidence=evidence,
                        source_bbox=list(region.bbox),
                        ink_bbox=[a + int(xs.min()), b + int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
                        outline_px=3. * pixel_scale, mask_pad_px=pad)
        if bubble:
            if region.bubble_bbox is None:
                if white_components is None:
                    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
                    white_components = cv2.connectedComponentsWithStats((gray > 225).astype(np.uint8))
                area = inferred_balloon_area(image, region, ink, box, white_components)
            else:
                from src.components.typesetter import interior_mask
                region._layout_light_core = False
                area = interior_mask(np.asarray(image.convert('RGB')), region)
            if getattr(region, '_layout_light_core', False):
                geometry['contour_source'] = 'light_core'
            contours, _ = cv2.findContours(area, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                contour = max(contours, key=cv2.contourArea)
                geometry['contour'] = cv2.approxPolyDP(contour, 1., True).reshape(-1, 2).tolist()
        if bubble and region.bubble_bbox is not None:
            bx, by, bw, bh = region.bubble_bbox
            letters = sum(not ch.isspace() for ch in region.translation)
            if bh >= bw * 2.6 and 2 <= letters <= 16 and not style.font_size_override:
                margin = max(3, round(min(bw, bh) * .1))
                geometry['writing_mode'] = 'vertical'
                geometry['ink_bbox'] = [bx + margin, by + margin, max(1, bw - 2*margin), max(1, bh - 2*margin)]
                geometry['angle'] = angle = 0.
        if not bubble:
            geometry['allow_vertical'] = region.block_type == 'sfx'
            if abs(angle) >= 3:
                from src.components.slanted_layout import source_lines
                rows = source_lines(ink, (a, b), region.bbox, angle)
                if rows:
                    geometry['source_lines'] = rows
        region.auto_layout = geometry
        style.rotation = angle
        if not bubble and style.stroke_mode == 'auto' and not style.fill_locked:
            style.fill_rgb = (18, 18, 18)
            style.stroke_rgb = (255, 255, 255)
            style.stroke_width = 3. * pixel_scale


def geometry_area(shape, region):
    """Восстановить сохранённую форму по исходнику, а не искать её после LaMa."""
    points = (region.auto_layout or {}).get('contour')
    if not isinstance(points, list) or len(points) < 3:
        return None

    try:
        polygon = np.asarray(points, dtype=np.float64)
        if polygon.ndim != 2 or polygon.shape[1] != 2 or len(points) > 4096 or not np.all(np.isfinite(polygon)):
            return None
        area = np.zeros(shape[:2], np.uint8)
        cv2.fillPoly(area, [np.clip(polygon, -1_000_000, 1_000_000).astype(np.int32)], 255)
        if (region.auto_layout or {}).get('kind') == 'bubble':
            from src.components.bubble_layout import covers_source
            if not covers_source(area, region):
                if (region.auto_layout or {}).get('contour_source') != 'light_core' or region.bubble_bbox is None:
                    return None
                bx,by,bw,bh=region.bubble_bbox
                tx,ty,tw,th=region.bbox
                cx,cy=round(tx+tw/2),round(ty+th/2)
                if (not (0<=cx<area.shape[1] and 0<=cy<area.shape[0] and area[cy,cx]) or
                        np.count_nonzero(area)<bw*bh*.3 or
                        np.count_nonzero(area[max(0,by):by+bh,max(0,bx):bx+bw])<np.count_nonzero(area)*.99):
                    return None
        return area
    except (TypeError, ValueError):
        return None


def fit_balloon_shape(area, region, text, font_path, lang, min_size=7, max_size=160, stroke_pad=0):
    """Подбор в локальной обратноповёрнутой форме, с проверкой реальных пикселей.

    Кегль перебирается сверху вниз: при смене числа строк более мелкий размер
    не обязан помещаться, если поместился крупный. ``stroke_pad`` — число или
    функция размера, та же обводка, что у финальной растеризации.
    """
    from PIL import ImageDraw, ImageFont
    from src.components.bubble_layout import layout_in_shape, shape_row_spans
    from src.components.typesetter import _composite_styled_layer, _field_center, _hyphenator
    ys, xs = np.where(area > 0)
    if not len(xs):
        return None, None, False
    a, b, c, d = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    cut = area[b:d, a:c]
    diagonal = math.ceil(math.hypot(*cut.shape)) + 24
    shape = np.zeros((diagonal, diagonal), np.uint8)
    offx, offy = (diagonal - cut.shape[1]) // 2, (diagonal - cut.shape[0]) // 2
    shape[offy:offy + cut.shape[0], offx:offx + cut.shape[1]] = cut
    origin_x, origin_y = a - offx, b - offy
    cx, cy = _field_center(region, (0., 0.))
    center = (cx - origin_x, cy - origin_y)
    angle = float(region.style.rotation)
    deskew = cv2.warpAffine(shape, cv2.getRotationMatrix2D(center, -angle, 1), (diagonal, diagonal), flags=cv2.INTER_NEAREST)
    inset = max(2, round(min(cut.shape) * .045))
    deskew = cv2.erode(deskew, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (inset * 2 + 1, inset * 2 + 1)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats((deskew > 0).astype(np.uint8))
    if count > 2:
        # После отступа тонкая перемычка может разделить фигурное облачко.
        # Строки одной реплики не должны прыгать между разными островками.
        label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        deskew = (labels == label).astype(np.uint8) * 255
    spans = shape_row_spans(deskew)
    dummy = ImageDraw.Draw(Image.new('L', (1, 1)))
    low = max(1, int(min_size))
    high = min(int(max_size), max(low, round(min(cut.shape) * .55)))
    selected = None
    spacing = float(region.style.letter_spacing or 0.0)
    local_region = copy.copy(region)
    local_region.bbox = (region.bbox[0] - origin_x, region.bbox[1] - origin_y, *region.bbox[2:])
    if region.bubble_bbox is not None:
        local_region.bubble_bbox = (region.bubble_bbox[0] - origin_x, region.bubble_bbox[1] - origin_y, *region.bubble_bbox[2:])
    local_region.text_position = None
    def attempt(size, hyphenator):
        pad = int(stroke_pad(size) if callable(stroke_pad) else stroke_pad)
        font = ImageFont.truetype(str(font_path), size)
        placed, fits = layout_in_shape(
            text, font, dummy, spans, hyphenator, 'center',
            letter_spacing=spacing, line_spacing=region.style.line_spacing, stroke_pad=pad,
        )
        if not fits:
            return None
        layer = Image.new('RGBA', (diagonal, diagonal))
        # Проверяем ту же растеризацию 2× и тот же поворот, что в финальном выводе.
        _composite_styled_layer(layer, placed, font, font_path, (255, 255, 255),
                                (255, 255, 255), pad, region.style, dummy, region=local_region)
        turned = np.asarray(layer)
        if np.any((turned[..., 3] > 20) & (shape == 0)):
            return None
        return ([(line, int(x + origin_x), int(y + origin_y)) for line, x, y in placed], font, True)

    for size in range(high, low - 1, -1):
        selected = attempt(size, _hyphenator(lang))
        if selected:
            # Умеренно уменьшаем кегль, если это убирает переносы внутри слов.
            if any(line.endswith('-') and line not in text.split() for line, _, _ in selected[0]):
                for whole_size in range(size, max(low, math.ceil(size * .82)) - 1, -1):
                    whole = attempt(whole_size, None)
                    if whole:
                        return whole
            return selected
    return selected or (None, None, False)


def adaptive_masks(image, regions, ordinary, free, grow_px=0):
    """Полный отступ от чернил SFX; соседние области речи защищены от ретуши."""
    ordinary, free = ordinary.copy(), free.copy()
    for region in regions:
        meta = region.auto_layout or {}
        if not meta or region.skip or not region.translation.strip():
            continue
        if meta.get('kind') == 'bubble' and region.bubble_bbox is not None:
            continue
        _, ink, (a, b, c, d) = source_ink(image, region)
        boundary = None
        if meta.get('kind') == 'free':
            crop = np.asarray(image.crop((a, b, c, d)))
            confirmed, inverse_outline = confirmed_light_ink(crop)
            if confirmed is not None and inverse_outline:
                ink = np.maximum(ink, smooth_line_mask(crop, confirmed))
                # Расширение не пересчитывает остальные строки и их отступ:
                # добираются только компоненты, пересекающие прежний край ROI.
                boundary = boundary_ink(image, region.bbox, (a, b, c, d))
        radius = max(1, min(64, round(float(meta.get('mask_pad_px', 8)))))
        if meta.get('kind') == 'bubble':
            radius = max(1, round(radius * .75))
        radius += max(0, int(grow_px))
        # Дилатация в расширенном ROI: прежний crop+5 обрезал отступ8px.
        xa, ya, xb, yb = max(0, a - radius), max(0, b - radius), min(image.width, c + radius), min(image.height, d + radius)
        local = np.zeros((yb - ya, xb - xa), np.uint8)
        local[b - ya:d - ya, a - xa:c - xa] = ink
        local = cv2.dilate(local, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1)))
        if boundary is not None:
            extra, (aa, bb, cc, dd) = boundary
            na, nb, nc, nd = min(xa, aa), min(ya, bb), max(xb, cc), max(yb, dd)
            expanded = np.zeros((nd-nb, nc-na), np.uint8)
            expanded[ya-nb:yb-nb, xa-na:xb-na] = local
            expanded[bb-nb:dd-nb, aa-na:cc-na] = np.maximum(expanded[bb-nb:dd-nb, aa-na:cc-na], extra)
            local = expanded
            xa, ya, xb, yb = na, nb, nc, nd
        if meta.get('kind') == 'bubble':
            area = geometry_area((image.height, image.width), region)
            if area is not None:
                local[area[ya:yb, xa:xb] == 0] = 0
            if region.bubble_bbox is None:
                # Толстая буква может соединиться с тонким контуром и исчезнуть
                # из геометрического фильтра. Восстанавливаем только её ядро,
                # не распространяя заливку по всей связанной обводке.
                joined = joined_speech_ink(image.crop((a, b, c, d)), region, (a, b), area)
                local[b - ya:d - ya, a - xa:c - xa] = np.maximum(
                    local[b - ya:d - ya, a - xa:c - xa], joined)
        else:
            for other in regions:
                if other.id == region.id or not is_balloon(other):
                    continue
                x, y, w, h = other.bbox
                chars = [ch for ch in region.text if ch.isalnum()]
                if (region.block_type == 'sfx' and 2 <= len(chars) <= 6 and
                        all('\u3040' <= ch <= '\u9fff' for ch in chars) and
                        min(xb,x+w)>max(xa,x) and min(yb,y+h)>max(ya,y)):
                    # Рамка высокой японской реплики включает пустые поля.
                    # В них может оказаться край крупного звука. Защищаем
                    # подтверждённые буквы речи, а не весь её прямоугольник.
                    _, protected, (pa,pb,pc,pd) = source_ink(image, other)
                    if np.count_nonzero(protected) >= 20:
                        protected = cv2.dilate(protected,np.ones((5,5),np.uint8))
                        left,top,right,bottom=max(xa,pa),max(ya,pb),min(xb,pc),min(yb,pd)
                        if right>left and bottom>top:
                            view=local[top-ya:bottom-ya,left-xa:right-xa]
                            view[protected[top-pb:bottom-pb,left-pa:right-pa]>0]=0
                        continue
                local[max(0, y - ya):max(0, min(yb, y + h) - ya), max(0, x - xa):max(0, min(xb, x + w) - xa)] = 0
        destination = free if meta.get('kind') == 'free' else ordinary
        # Удалить старую маску лишь в боксе этой надписи; остальные регионы не затирать.
        destination[ya:yb, xa:xb] = np.maximum(destination[ya:yb, xa:xb], local)
    return ordinary, free


def joined_speech_ink(crop, region, origin, area=None):
    """Ограниченный добор толстых букв, соединённых с тонким краем облачка."""
    gray = cv2.cvtColor(np.asarray(crop.convert('RGB')), cv2.COLOR_RGB2GRAY)
    result = np.zeros(gray.shape, np.uint8)
    if not gray.size or np.percentile(gray, 60) < 225:
        return result
    scale = max(.5, float((region.auto_layout or {}).get('outline_px', 3)) / 3)
    radius = max(1.8, scale * 1.2)
    dark = (gray < 160).astype(np.uint8)
    core = (cv2.distanceTransform(dark, cv2.DIST_L2, 5) > radius).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(core)
    a, b = origin
    x, y, w, h = region.bbox
    for idx in range(1, count):
        cx, cy, cw, ch, pixels = stats[idx]
        if (pixels < max(3, scale * scale) or ch > h * .65 or cw > w * .65 or
                not (x <= a + cx + cw / 2 <= x + w and y <= b + cy + ch / 2 <= y + h)):
            continue
        component = labels == idx
        if area is not None and np.mean(area[b:b + gray.shape[0], a:a + gray.shape[1]][component] > 0) < .6:
            continue
        result[component] = 255
    grow = max(2, math.ceil(radius * 1.6))
    result = cv2.dilate(result, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    result[dark == 0] = 0
    pad = max(1, round(scale))
    return cv2.dilate(result, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1)))

def source_ink(image, region):
    """Чернила локального кропа без необходимости держать маску всей страницы на регион."""
    (x, y, w, h) = region.bbox
    (a, b, c, d) = (max(0, x - 5), max(0, y - 5), min(image.width, x + w + 5), min(image.height, y + h + 5))
    if c <= a or d <= b:
        return Image.new('RGB', (1, 1)), np.zeros((0, 0), np.uint8), (0, 0, 0, 0)
    crop = image.crop((a, b, c, d))
    local = copy.deepcopy(region)
    local.bbox = (x - a, y - b, w, h)
    # Исходный тип нужен сегментатору: ниже тип подменяется, чтобы снять чернила.
    local._mask_as = region.block_type
    local._mask_bubble = region.bubble_bbox is not None
    local.bubble_bbox = None
    local.block_type = 'sfx'
    capture = {}
    segment_regions(crop, [local], capture_ink=capture)
    ink = capture.get(local.id, np.zeros((crop.height, crop.width), np.uint8))
    # Короткий CJK-звук на бумаге может не иметь различимого ореола.
    # Замкнутые тёмные ядра сохраняются целиком: фильтр линий иначе
    # отбрасывает толстый крюк буквы как фрагмент рисунка.
    chars = [ch for ch in region.text if ch.isalnum()]
    if (region.block_type == 'sfx' and 2 <= len(chars) <= 6 and
            all('\u3040' <= ch <= '\u9fff' for ch in chars)):
        gray = cv2.cvtColor(np.asarray(crop.convert('RGB')), cv2.COLOR_RGB2GRAY)
        if np.mean(gray > 180) >= .6:
            count, labels, stats, _ = cv2.connectedComponentsWithStats((gray < 80).astype(np.uint8))
            cores = [i for i in range(1,count) if stats[i,4] >= 8 and
                     stats[i,0] > 0 and stats[i,1] > 0 and
                     stats[i,0]+stats[i,2] < crop.width and stats[i,1]+stats[i,3] < crop.height and
                     stats[i,2] <= w*.9 and stats[i,3] <= h*1.1]
            large = [i for i in cores if stats[i,2] >= w*.05 and stats[i,3] >= h*.15]
            if len(large) >= 2:
                ink = np.maximum(ink, np.isin(labels, cores).astype(np.uint8)*255)

    if getattr(local, "_outline_ink", False):
        region._outline_ink = True
    if region.block_type != 'sfx' and (not region.document):
        (count, labels, stats, _) = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8))
        candidates = [s[3] for s in stats[1:] if s[4] >= 6 and s[3] > 3 and (s[2] < crop.width * 0.4) and (s[3] < crop.height * 0.7)]
        if len(candidates) >= 5:
            typical = float(np.percentile(candidates, 60))
            kept = [i for i in range(1, count) if stats[i, 4] >= 3 and stats[i, 3] <= max(8, typical * 2.0) and (stats[i, 2] <= max(12, typical * 3.0))]
            filtered = np.isin(labels, kept).astype(np.uint8) * 255
            if np.count_nonzero(filtered) > 20:
                ink = filtered
            if region.bubble_bbox is None and region.class_name == 'text_bubble' and (len(candidates) >= 8):
                (rough, _) = text_angle(ink)
                (count, lab, st, centers) = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8))
                rad = math.radians(rough)
                projected = sorted(((math.sin(rad) * centers[i, 0] + math.cos(rad) * centers[i, 1], i) for i in range(1, count) if st[i, 4] >= 3))
                groups = []
                for (ordinate, idx) in projected:
                    if not groups or ordinate - groups[-1][-1][0] > typical * 0.55:
                        groups.append([])
                    groups[-1].append((ordinate, idx))
                reliable = [g for g in groups if len(g) >= 3]
                ids = [idx for g in reliable for (_, idx) in g]
                candidate = np.isin(lab, ids).astype(np.uint8) * 255
                if reliable and np.count_nonzero(candidate) > np.count_nonzero(ink) * 0.4:
                    ink = candidate
    # Фильтр геометрии может принять соединённые обводкой строки за крупное
    # пятно. Подтверждённый ореол нельзя терять на втором этапе очистки чернил.
    if region.block_type != 'sfx' and not region.document:
        outlined = _outlined_text_mask(np.asarray(crop))
        if outlined is not None:
            ink = np.maximum(ink, outlined)
        confirmed, _ = confirmed_light_ink(np.asarray(crop))
        if confirmed is not None:
            ink = np.maximum(ink, confirmed)
            region._retouch_preserve_background = True
    if (region.bubble_bbox is None and is_balloon(region) and
            sum(ch.isalnum() for ch in region.text) >= 8):
        ink = _supported_speech_rows(ink)
    return (crop, ink, (a, b, c, d))


def _supported_speech_rows(ink):
    """Не включать отдельные штрихи рисунка в оболочку непривязанной речи.

    Обводка и ресэмплинг могут добавить пару компонентов далеко от строк.
    Фильтр срабатывает только при нескольких подтверждённых рядах букв;
    короткие реплики и неоднозначные наборы компонентов остаются прежними.
    """
    count, labels, stats, centers = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8))
    significant = [i for i in range(1, count) if stats[i, 4] >= 8 and stats[i, 3] >= 5]
    if len(significant) < 8:
        return ink
    typical = float(np.percentile([stats[i, 3] for i in significant], 60))
    angle, _ = text_angle(ink)
    rad = math.radians(angle)
    normal = np.sin(rad) * centers[:, 0] + np.cos(rad) * centers[:, 1]
    ordered = sorted(significant, key=lambda i: normal[i])
    groups = []
    for idx in ordered:
        if not groups or normal[idx] - normal[groups[-1][-1]] > typical * .7:
            groups.append([])
        groups[-1].append(idx)
    supported = [g for g in groups if sum(stats[i, 3] >= typical * .4 for i in g) >= 3]
    if not supported:
        return ink
    # Точки и дефисы сохраняются рядом с найденной строкой, но не создают
    # собственный подтверждённый ряд из мелких штрихов рисунка.
    ids = [i for i in range(1, count) if any(
        min(normal[j] for j in group) - typical * .35 <= normal[i] <=
        max(normal[j] for j in group) + typical * .35 for group in supported)]
    filtered = np.isin(labels, ids).astype(np.uint8) * 255
    if np.count_nonzero(filtered) >= np.count_nonzero(ink) * .75:
        return filtered
    return ink

def text_angle(ink):
    """Оценка направления строк по концентрации горизонтальной проекции после поворота."""
    if np.count_nonzero(ink) < 15:
        return (0.0, {'reason': 'мало чернил'})
    (ys, xs) = np.where(ink > 0)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if max(ink.shape) > 420:
        scale = 420 / max(ink.shape)
        ink = cv2.resize(ink, (max(1, round(ink.shape[1] * scale)), max(1, round(ink.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    ink = (ink > 127).astype(np.uint8)
    side = math.ceil(math.hypot(*ink.shape)) + 8
    padded = np.zeros((side, side), np.uint8)
    y = (side - ink.shape[0]) // 2
    x = (side - ink.shape[1]) // 2
    padded[y:y + ink.shape[0], x:x + ink.shape[1]] = ink
    scores = []
    for angle in range(-35, 36):
        matrix = cv2.getRotationMatrix2D((side / 2, side / 2), -angle, 1)
        rotated = cv2.warpAffine(padded, matrix, (side, side), flags=cv2.INTER_LINEAR)
        projection = rotated.sum(axis=1, dtype=np.float64)
        scores.append((float(np.dot(projection, projection)), angle))
    (best, angle) = max(scores)
    zero = scores[35][0]
    gain = best / max(zero, 1)
    if abs(angle) < 3 or gain < 1.055 or abs(angle) == 35:
        return (0.0, {'raw_angle': angle, 'gain': round(gain, 3), 'reason': 'недостаточная уверенность'})
    # Повторное измерение на сглаженной маске устраняет ступеньку целого градуса.
    smooth = padded.astype(np.float32)
    refined = []
    for candidate in np.arange(angle - 1., angle + 1.01, .1):
        matrix = cv2.getRotationMatrix2D((side / 2, side / 2), -float(candidate), 1)
        rotated = cv2.warpAffine(smooth, matrix, (side, side), flags=cv2.INTER_LINEAR)
        projection = rotated.sum(axis=1, dtype=np.float64)
        refined.append((float(np.dot(projection, projection)), float(candidate)))
    angle = round(max(refined)[1], 2)
    return (float(angle), {'raw_angle': angle, 'gain': round(gain, 3), 'reason': 'проекция строк'})

def inferred_balloon_area(image, region, ink, box, white_components=None):
    """Консервативное поле строк по оболочке букв, если детектор не привязал облачко."""
    (ys, xs) = np.where(ink > 0)
    area = np.zeros((image.height, image.width), np.uint8)
    if len(xs) < 3:
        return area
    (a, b, c, d) = box
    if white_components is None:
        gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
        white_components = cv2.connectedComponentsWithStats((gray > 225).astype(np.uint8))
    count, labels, stats, _ = white_components
    best = None
    for idx in range(1, count):
        (x, y, w, h, area_size) = stats[idx]
        if (w > region.bbox[2] * 3 or h > region.bbox[3] * 3 or
                w * h > region.bbox[2] * region.bbox[3] * 3 or
                area_size < (c - a) * (d - b) * 0.15 or x == 0 or y == 0 or (x + w >= image.width) or
                (y + h >= image.height) or x >= c or y >= d or x + w <= a or y + h <= b):
            continue
        component = (labels[y:y+h, x:x+w] == idx).astype(np.uint8)
        (contours, _) = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = cv2.drawContours(np.zeros_like(component), contours, -1, 255, -1)
        xa, ya, xb, yb = max(a, x), max(b, y), min(c, x+w), min(d, y+h)
        covered = int(np.count_nonzero((filled[ya-y:yb-y, xa-x:xb-x] > 0) & (ink[ya-b:yb-b, xa-a:xb-a] > 0)))
        if covered >= np.count_nonzero(ink) * 0.8 and (best is None or covered > best[0]):
            best = (covered, filled, (x, y, w, h))
    if best is not None:
        x, y, w, h = best[2]
        area[y:y+h, x:x+w] = best[1]
        return cv2.erode(area, np.ones((5, 5), np.uint8))
    points = np.stack([xs + a, ys + b], axis=1).astype(np.int32)
    hull = cv2.convexHull(points)
    cv2.fillConvexPoly(area, hull, 255)
    pad = max(4, round(min(c - a, d - b) * 0.035))
    area = cv2.dilate(area, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad * 2 + 1, pad * 2 + 1)))
    # Оболочка двух наклонных строк пересекает выемки фигурного облачка.
    # Внутри ограниченной оболочки обводка снова разделяет белый фон:
    # оставляем только части, действительно окружающие исходные буквы.
    yy, xx = np.where(area > 0)
    left, top, right, bottom = int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1
    local_gray = cv2.cvtColor(np.asarray(image.crop((left, top, right, bottom)).convert('RGB')), cv2.COLOR_RGB2GRAY)
    local_area = area[top:bottom, left:right]
    bright = ((local_gray > 180) & (local_area > 0)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    source = np.zeros_like(local_area)
    xa, ya, xb, yb = max(left, a), max(top, b), min(right, c), min(bottom, d)
    source[ya - top:yb - top, xa - left:xb - left] = ink[ya - b:yb - b, xa - a:xb - a]
    refined = np.zeros_like(local_area)
    for idx in range(1, count):
        if stats[idx, cv2.CC_STAT_AREA] < pad * pad:
            continue
        contours, _ = cv2.findContours((labels == idx).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = cv2.drawContours(np.zeros_like(local_area), contours, -1, 255, -1)
        if np.count_nonzero((filled > 0) & (source > 0)) >= max(8, np.count_nonzero(ink) * .02):
            refined = np.maximum(refined, filled)
    if np.count_nonzero((refined > 0) & (source > 0)) >= np.count_nonzero(ink) * .9:
        area[top:bottom, left:right] = refined
    return area
