"""Дополнительный поиск содержательных надписей со строгими координатами."""
from __future__ import annotations

import json
import math
import unicodedata
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image
from src.models import TextRegion

_TYPES = ('sfx', 'dialogue', 'narration', 'title')
_FIELDS = {name: {'type': 'number', 'minimum': 0, 'maximum': 1000}
           for name in ('x0', 'y0', 'x1', 'y1')}
_FIELDS.update(text={'type': 'string'}, type={'type': 'string', 'enum': list(_TYPES)})
SCHEMA = {'type': 'object', 'properties': {'blocks': {'type': 'array', 'maxItems': 100,
          'items': {'type': 'object', 'properties': _FIELDS, 'required': list(_FIELDS),
                    'additionalProperties': False}}}, 'required': ['blocks'], 'additionalProperties': False}


def parse_discovery(payload, size, existing):
    """Принять только конечные xyxy; одинаковое слово в другом месте не дубль."""
    result = []
    if not isinstance(payload, dict) or not isinstance(payload.get('blocks'), list):
        return result
    width, height = size
    for item in payload['blocks'][:100]:
        if not isinstance(item, dict) or item.get('type') not in _TYPES:
            continue
        text = item.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            continue
        values = [item.get(key) for key in ('x0', 'y0', 'x1', 'y1')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            continue
        x0, y0, x1, y1 = values
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            continue
        x, y, right, bottom = (round(x0 * width / 1000), round(y0 * height / 1000),
                               round(x1 * width / 1000), round(y1 * height / 1000))
        w, h = right - x, bottom - y
        if min(w, h) < 4:
            continue
        duplicate = False
        for region in [*existing, *result]:
            ox, oy, ow, oh = region.bbox
            overlap = max(0, min(right, ox + ow) - max(x, ox)) * max(0, min(bottom, oy + oh) - max(y, oy))
            if overlap / max(1, min(w * h, ow * oh)) > .4:
                duplicate = True
                break
        if duplicate:
            continue
        ident = max((r.id for r in [*existing, *result]), default=0) + 1
        result.append(TextRegion(ident, (x, y, w, h), text=text.strip(), block_type=item['type'],
                                 class_name='text_bubble' if item['type'] == 'dialogue' else 'text_free',
                                 confidence=.6, order=len(existing) + len(result)))
    return result


def discover_missing_text(image, regions, client, max_side=1800):
    """Один последовательный OCR-запрос, перевод выполняется общим переводчиком."""
    shown = image.copy()
    shown.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    known = [{'text': r.text, 'x0': round(r.bbox[0] / image.width * 1000),
              'y0': round(r.bbox[1] / image.height * 1000),
              'x1': round((r.bbox[0] + r.bbox[2]) / image.width * 1000),
              'y1': round((r.bbox[1] + r.bbox[3]) / image.height * 1000)} for r in regions]
    prompt = ('Find readable text MISSING from the existing list. Include sound effects, action captions, '
              'narration, thoughts and missed speech. Return the literal source text, do not translate. '
              'Exclude artwork, motion lines, signatures, credits, watermarks and social-media controls. '
              'Do not repeat existing blocks. Each box uses explicit x0,y0,x1,y1 corners normalized '
              'to 0..1000 of the FULL image. For ordinary labels with meaningful story content use narration. '
              'Use sfx only for sounds/short actions, never for a full thought. Return blocks=[] if none. '
              'Existing list: ' + json.dumps(known, ensure_ascii=False))
    payload = client.chat_json(prompt, SCHEMA, 'missing_text', images=[shown], max_tokens=4096)
    extras = parse_discovery(payload, image.size, regions)
    return refine_discovery(image, extras, regions)


def refine_discovery(image, regions, existing=()):
    """Уточнить добавленные OCR-рамки по буквам или локально проверенному SFX.

    Координаты VLM иногда указывают на обводку рядом с короткой репликой.
    Перенос разрешён только к отдельным тёмным буквам внутри замкнутой
    светлой области. Звук переносится только при точном совпадении текста
    с независимым локальным OCR; ручные рамки не исправляются.
    """
    for region in regions:
        if (region.block_type == 'sfx' and not region.manual and not region.edited
                and not region.document and region.bubble_bbox is None):
            _refine_sfx(image, region, [*existing, *(other for other in regions if other is not region)])
            continue
        if (region.manual or region.edited or region.document or region.bubble_bbox or
                region.block_type not in ('dialogue', 'narration') or
                not 2 <= sum(c.isalnum() for c in region.text) <= 80):
            continue
        x, y, w, h = region.bbox
        radius = math.ceil(max(w, h) * 2.5)
        xa, ya = max(0, x - radius), max(0, y - radius)
        xb, yb = min(image.width, x + w + radius), min(image.height, y + h + radius)
        gray = cv2.cvtColor(np.asarray(image.crop((xa, ya, xb, yb)).convert('RGB')), cv2.COLOR_RGB2GRAY)
        count, labels, stats, _ = cv2.connectedComponentsWithStats((gray >= 225).astype(np.uint8))
        choices = []
        for ident in range(1, count):
            bx, by, bw, bh, pixels = (int(v) for v in stats[ident])
            if (bx == 0 or by == 0 or bx + bw >= gray.shape[1] or by + bh >= gray.shape[0] or
                    pixels < w * h * .45 or bw * bh > w * h * 12):
                continue
            overlap = max(0, min(x + w, xa + bx + bw) - max(x, xa + bx)) * max(0, min(y + h, ya + by + bh) - max(y, ya + by))
            if overlap < w * h * .08:
                continue
            part = (labels[by:by + bh, bx:bx + bw] == ident).astype(np.uint8)
            contours, _ = cv2.findContours(part, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            shape = cv2.drawContours(np.zeros_like(part), contours, -1, 255, -1)
            safe = cv2.erode(shape, np.ones((5, 5), np.uint8))
            dark = ((gray[by:by + bh, bx:bx + bw] < 150) & (shape > 0)).astype(np.uint8)
            n, glyphs, glyph_stats, _ = cv2.connectedComponentsWithStats(dark)
            kept = []
            for idx in range(1, n):
                gx, gy, gw, gh, area = glyph_stats[idx]
                component = glyphs == idx
                if (area >= max(3, w * h * .0002) and gh <= h * .85 and
                        gw <= w * 1.1 and not np.any(component & (safe == 0))):
                    kept.append(idx)
            letters = [idx for idx in kept if glyph_stats[idx, 3] >= max(5, min(w, h) * .12)]
            if not 2 <= len(letters) <= sum(c.isalnum() for c in region.text) * 3:
                continue
            ink = np.isin(glyphs, kept)
            ys, xs = np.where(ink)
            tx, ty = xa + bx + int(xs.min()), ya + by + int(ys.min())
            tw, th = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
            if abs(tx + tw / 2 - x - w / 2) > max(w, h) * 1.5 or abs(ty + th / 2 - y - h / 2) > max(w, h) * 1.5:
                continue
            if any(max(0, min(tx + tw, ox + ow) - max(tx, ox)) * max(0, min(ty + th, oy + oh) - max(ty, oy)) > min(tw * th, ow * oh) * .4
                   for ox, oy, ow, oh in (other.bbox for other in existing)):
                continue
            distance = abs(tx + tw / 2 - x - w / 2) + abs(ty + th / 2 - y - h / 2)
            choices.append((distance, (tx, ty, tw, th), (xa + bx, ya + by, bw, bh)))
        if len(choices) == 1:
            _, region.bbox, region.bubble_bbox = choices[0]
            region.block_type = 'dialogue'
            region.class_name = 'text_bubble'
            region.auto_layout = None
    return regions


@lru_cache(maxsize=1)
def _discovery_ocr():
    """Один лениво загружаемый локальный движок для уточнения дополнительных звуков."""
    from src.components.rapid_ocr import RapidOcr
    return RapidOcr(min_confidence=.75, intra_op_threads=2)


def _source_word(text):
    """Сравнивать буквы без регистра, декоративных дефисов и пунктуации."""
    return ''.join(ch for ch in unicodedata.normalize('NFKC', text).casefold() if ch.isalnum())


def _refine_sfx(image, region, existing):
    """Выбрать явно ближайшее точное слово либо две части одной надписи."""
    wanted = _source_word(region.text)
    if not 2 <= len(wanted) <= 40:
        return
    x, y, w, h = region.bbox
    pad = max(w, h)
    xa, ya = max(0, x - pad), max(0, y - pad)
    xb, yb = min(image.width, x + w + pad), min(image.height, y + h + pad)
    try:
        words = _discovery_ocr()._words(image.crop((xa, ya, xb, yb)))
    except Exception:
        # Нет локальных моделей / распознавание не удалось: прежняя рамка
        # сохраняется. Загрузка компонентов и угадывание по рисунку запрещены.
        return
    words = [word for word in words if word.confidence >= .75]
    boxes = [word.bbox for word in words if _source_word(word.text) == wanted]
    for first in words:
        prefix = _source_word(first.text)
        if len(prefix) < 2 or not wanted.startswith(prefix) or prefix == wanted:
            continue
        for second in words:
            if second is first or prefix + _source_word(second.text) != wanted:
                continue
            fx, fy, fw, fh = first.bbox
            sx, sy, sw, sh = second.bbox
            gap_x = max(0, max(fx, sx) - min(fx + fw, sx + sw))
            gap_y = max(0, max(fy, sy) - min(fy + fh, sy + sh))
            if (gap_x > max(fh, sh) * .8 or gap_y > max(fh, sh) * .8
                    or math.hypot(fx + fw / 2 - sx - sw / 2, fy + fh / 2 - sy - sh / 2) > max(fw, fh, sw, sh) * 1.5):
                continue
            left, top = min(fx, sx), min(fy, sy)
            boxes.append((left, top, max(fx + fw, sx + sw) - left, max(fy + fh, sy + sh) - top))
    candidates = []
    for tx, ty, tw, th in set(boxes):
        if (min(tx, ty) < 0 or min(tw, th) < 3 or tx + tw > xb - xa or ty + th > yb - ya
                or not .1 <= tw * th / max(1, w * h) <= 6):
            continue
        tx, ty = tx + xa, ty + ya
        distance = math.hypot(tx + tw / 2 - x - w / 2, ty + th / 2 - y - h / 2)
        if distance > pad * 1.5:
            continue
        if any(max(0, min(tx + tw, ox + ow) - max(tx, ox)) * max(0, min(ty + th, oy + oh) - max(ty, oy)) > min(tw * th, ow * oh) * .4
               for ox, oy, ow, oh in (other.bbox for other in existing)):
            continue
        candidates.append((distance, (tx, ty, tw, th)))
    candidates.sort()
    # Повторённый звук допустим, если одна рамка заметно ближе к ожидаемой.
    # При равных или близких расстояниях сохраняем прежнюю локализацию.
    if not candidates or (len(candidates) > 1 and candidates[1][0] - candidates[0][0] < max(8, pad * .2)):
        return
    region.bbox = candidates[0][1]
    region.auto_layout = None
