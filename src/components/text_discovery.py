"""Дополнительный поиск содержательных надписей со строгими координатами."""
from __future__ import annotations

import json
import math

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
    return parse_discovery(payload, image.size, regions)
