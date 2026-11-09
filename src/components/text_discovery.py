"""Дополнительный поиск содержательных надписей со строгими координатами."""
from __future__ import annotations

import json
import math
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image
from src.models import TextRegion

_TYPES = ('sfx', 'dialogue', 'narration', 'title')
_FIELDS = {name: {'type': 'number', 'minimum': 0, 'maximum': 1000}
           for name in ('x0', 'y0', 'x1', 'y1')}
_FIELDS.update(text={'type': 'string'}, type={'type': 'string', 'enum': list(_TYPES)})
SCHEMA = {'type': 'object', 'properties': {'blocks': {'type': 'array', 'maxItems': 24,
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
            # Неточная рамка кропа может захватить край уже известной
            # вертикальной реплики: повторно переводить её фрагмент нельзя.
            source = _source_word(text)
            known = _source_word(region.text)
            if (overlap > 0 and len(source) >= 3 and len(known) >= 3 and
                    (source in known or known in source)):
                duplicate = True
                break
            if (overlap > min(w*h, ow*oh)*.08 and 4 <= len(source) < len(known)*.85 and
                    sum(match.size for match in SequenceMatcher(None, source, known, autojunk=False).get_matching_blocks())
                    >= len(source)*.8):
                duplicate = True
                break
        if duplicate:
            continue
        ident = max((r.id for r in [*existing, *result]), default=0) + 1
        result.append(TextRegion(ident, (x, y, w, h), text=text.strip(), block_type=item['type'],
                                 class_name='text_bubble' if item['type'] == 'dialogue' else 'text_free',
                                 confidence=.6, order=len(existing) + len(result)))
    return result


def _discovery_tiles(size, max_side):
    """До девяти перекрывающихся кропов с полным покрытием страницы."""
    width, height = size
    if max(size) <= max_side and (max(size) < 1500 or max(size) <= min(size) * 1.25):
        return [(0, 0, width, height)]
    # Кропы сохраняют контекст панели; число запросов ограничено даже для ленты.
    # Три кропа с шагом не больше 80% стороны покрывают 2.6 стороны.
    # Деление длинной оси на три оставляло почти нулевое перекрытие.
    # Два пикселя запаса сохраняют 20% и после округления начальных точек.
    side = max(min(max_side, min(size)), math.ceil((max(size) + 2) / 2.6))
    def starts(length):
        if length <= side:
            return [0]
        count = min(3, math.ceil((length - side) / (side * .8)) + 1)
        return [round(i * (length - side) / (count - 1)) for i in range(count)]
    return [(x, y, min(width, x + side), min(height, y + side))
            for y in starts(height) for x in starts(width)]


def _verify_sfx(image, region, client):
    """Подтвердить исходные буквы и их рамку в локальном контексте VLM."""
    x, y, w, h = region.bbox
    pad = max(24, round(max(w, h) * .75))
    a, b = max(0, x - pad), max(0, y - pad)
    c, d = min(image.width, x + w + pad), min(image.height, y + h + pad)
    crop = image.crop((a, b, c, d))
    crop.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    prompt = ('Locate this exact source text in the crop: ' + json.dumps(region.text, ensure_ascii=False) +
              '. Return its literal text and a tight box around ALL its letters, excluding nearby artwork '
              'and other words. Coordinates x0,y0,x1,y1 are 0..1000 of this CROP. '
              'Do not translate or invent missing letters. If it is not visible return blocks=[].')
    payload = client.chat_json(prompt, SCHEMA, 'verify_missing_text', images=[crop], max_tokens=1024)
    candidates = parse_discovery(payload, (c-a, d-b), [])
    wanted = _source_word(region.text)
    candidates = [r for r in candidates if _source_word(r.text) == wanted]
    if len(candidates) != 1:
        return False
    tx, ty, tw, th = candidates[0].bbox
    # Повтор слова в запросе локализации провоцирует подтверждение даже
    # соседнего рисунка. Читаем только предложенную рамку без ожидаемого текста.
    reading = client.chat_json(
        'Read all visible source text in this crop literally. Do not translate. '
        'Return text="" if there are no readable letters. Do not infer cropped letters.',
        {'type': 'object', 'properties': {'text': {'type': 'string'}},
         'required': ['text'], 'additionalProperties': False},
        'read_missing_text', images=[image.crop((tx+a, ty+b, tx+a+tw, ty+b+th))],
        max_tokens=1024,
    )
    read_text = reading.get('text') if isinstance(reading, dict) else None
    if not isinstance(read_text, str) or not read_text.strip():
        return False
    if wanted:
        matches = _source_word(read_text) == wanted
    else:
        # Знаки «?!» тоже содержательны, пустой кроп им не равен.
        matches = ''.join(unicodedata.normalize('NFKC', read_text).split()) == ''.join(
            unicodedata.normalize('NFKC', region.text).split())
    if not matches:
        return False
    region.bbox = (tx+a, ty+b, tw, th)
    return True


def discover_missing_text(image, regions, client, max_side=1800, warnings=None):
    """Последовательный поиск по перекрывающимся кропам с проверкой звуков."""
    extras = []
    attempts = 0
    completed_tiles = 0
    tile_error = None
    tiles = _discovery_tiles(image.size, max_side)
    limit_reported = False
    for tile_index, (a, b, c, d) in enumerate(tiles):
        # Неизрасходованный бюджет переносится вперёд; первый фрагмент
        # не может потратить все проверки на ложные предложения.
        tile_budget = (24 - attempts) // (len(tiles) - tile_index)
        tile_attempts = 0
        budget_reported = False
        shown = image.crop((a, b, c, d))
        shown.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        known = [{'text': r.text, 'x0': round((r.bbox[0]-a)/(c-a)*1000),
                  'y0': round((r.bbox[1]-b)/(d-b)*1000),
                  'x1': round((r.bbox[0]+r.bbox[2]-a)/(c-a)*1000),
                  'y1': round((r.bbox[1]+r.bbox[3]-b)/(d-b)*1000)}
                 for r in [*regions, *extras]
                 if r.bbox[0] >= a and r.bbox[1] >= b
                 and r.bbox[0]+r.bbox[2] <= c and r.bbox[1]+r.bbox[3] <= d]
        prompt = ('Find readable text MISSING from the existing list in this crop. '
                  'Include sound effects in every writing system, '
                  'action caption, narration, thought and missed speech. Return literal source text; '
                  'keep the original writing system. List only text actually visible at each location. '
                  'Exclude artwork, motion lines, signatures, credits, watermarks and social-media controls. '
                  'Do not repeat existing blocks. Each tight box encloses ALL letters and uses explicit '
                  'x0,y0,x1,y1 corners normalized to 0..1000 of this CROP. '
                  'For ordinary story labels use narration. Use sfx only for sounds/short actions, '
                  'never a full thought. Return blocks=[] if none. Existing list: '
                  + json.dumps(known, ensure_ascii=False))
        try:
            payload = client.chat_json(prompt, SCHEMA, 'missing_text', images=[shown], max_tokens=4096)
        except Exception as exc:
            tile_error = exc
            if warnings is not None:
                warnings.append(f'VLM не проверил фрагмент страницы: {type(exc).__name__}')
            continue
        completed_tiles += 1
        for region in parse_discovery(payload, (c-a, d-b), []):
            x, y, w, h = region.bbox
            region.bbox = (x+a, y+b, w, h)
            # Общее ограничение защищает от неограниченного числа crop-запросов.
            if len(extras) >= 24:
                if warnings is not None and not limit_reported:
                    warnings.append('Пропущены дополнительные блоки: предел 24 подтверждённых областей')
                    limit_reported = True
                continue
            if region.block_type in _TYPES:
                if tile_attempts >= tile_budget:
                    if warnings is not None and not budget_reported:
                        warnings.append('Пропущены дополнительные надписи: исчерпан бюджет проверки фрагмента')
                        budget_reported = True
                    continue
                tile_attempts += 1
                attempts += 1
                # Уточнение обязано предшествовать независимому чтению:
                # проверенная рамка больше не переносится к соседним буквам.
                refine_discovery(image, [region], [*regions, *extras])
                try:
                    verified = _verify_sfx(image, region, client)
                except Exception as exc:
                    if warnings is not None:
                        warnings.append(f'VLM не проверил кроп дополнительной надписи: {type(exc).__name__}')
                    continue
                if not verified:
                    if warnings is not None:
                        warnings.append('VLM не подтвердил рамку дополнительного звука' if region.block_type == 'sfx'
                                        else 'VLM не подтвердил рамку дополнительного текста')
                    continue
            x, y, w, h = region.bbox
            mapped = dict(text=region.text, type=region.block_type, x0=x/image.width*1000,
                          y0=y/image.height*1000, x1=(x+w)/image.width*1000, y1=(y+h)/image.height*1000)
            extras.extend(parse_discovery({'blocks': [mapped]}, image.size, [*regions, *extras]))
    # Полный отказ остаётся ошибкой для общего обработчика пайплайна.
    # Частичный результат сохраняется вместе с явными предупреждениями.
    if completed_tiles == 0 and tile_error is not None:
        raise tile_error
    return extras


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
    if not candidates:
        previous = region.bbox
        _refine_outlined_sfx(image, region, existing)
        if region.bbox == previous:
            _refine_plain_cjk_sfx(image, region, existing)
        return
    if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < max(8, pad * .2):
        return
    region.bbox = candidates[0][1]
    region.auto_layout = None


def _refine_outlined_sfx(image, region, existing):
    """Добрать цельную обведённую надпись, которую стилизованный OCR не прочёл.

    Требуются контрастные ядра с тонким ореолом и единственная группа,
    пересекающая исходную рамку. Границы соседних регионов защищены.
    """
    from src.components.sfx_ink import outlined_glyphs
    x, y, w, h = region.bbox
    pad = max(w, h)
    a, b, c, d = max(0, x-pad), max(0, y-pad), min(image.width, x+w+pad), min(image.height, y+h+pad)
    mask = outlined_glyphs(np.asarray(image.crop((a,b,c,d)).convert('RGB')), reject_cut_cores=True)
    if mask is None:
        return
    radius = max(3, min(16, round(min(w,h) * .12)))
    grouped = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius*2+1,radius*2+1)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats((grouped > 0).astype(np.uint8))
    choices = []
    for idx in range(1,count):
        if np.count_nonzero(labels[y-b:y+h-b,x-a:x+w-a] == idx) < max(8,w*h*.015):
            continue
        ys,xs=np.where((labels==idx) & (mask>0))
        if not len(xs):
            continue
        tx,ty,tw,th=a+int(xs.min()),b+int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)
        if not .5 <= tw*th/max(1,w*h) <= 4 or max(tw/w,th/h) > 3:
            continue
        if any(max(0,min(tx+tw,ox+ow)-max(tx,ox))*max(0,min(ty+th,oy+oh)-max(ty,oy)) > min(tw*th,ow*oh)*.25
               for ox,oy,ow,oh in (other.bbox for other in existing if not other.skip)):
            continue
        choices.append((tx,ty,tw,th))
    if len(choices)==1:
        region.bbox=choices[0]
        region.auto_layout=None


def _refine_plain_cjk_sfx(image, region, existing):
    """Крупные иероглифические звуки без различимого ореола на светлом поле.

    Нужна группа сравнимых ядер рядом с исходной рамкой. Рамки речи,
    соседних звуков и обрезанные компоненты рисунка не входят в группу.
    """
    letters=[ch for ch in region.text if ch.isalnum()]
    if not 2<=len(letters)<=6 or not all('\u3040'<=ch<='\u9fff' for ch in letters):
        return
    x,y,w,h=region.bbox
    pad=max(w,h)
    a,b,c,d=max(0,x-pad),max(0,y-pad),min(image.width,x+w+pad),min(image.height,y+h+pad)
    gray=cv2.cvtColor(np.asarray(image.crop((a,b,c,d)).convert('RGB')),cv2.COLOR_RGB2GRAY)
    count,labels,stats,_=cv2.connectedComponentsWithStats((gray<80).astype(np.uint8))
    cores=[]
    def protected(tx,ty,tw,th):
        return any(max(0,min(tx+tw,ox+ow)-max(tx,ox))*max(0,min(ty+th,oy+oh)-max(ty,oy))>min(tw*th,ow*oh)*.2
                   for ox,oy,ow,oh in (other.bbox for other in existing if not other.skip))
    for idx in range(1,count):
        xx,yy,ww,hh,pixels=map(int,stats[idx])
        tx,ty=xx+a,yy+b
        if (xx==0 or yy==0 or xx+ww==gray.shape[1] or yy+hh==gray.shape[0] or
                not h*.18<=hh<=h*1.2 or not w*.06<=ww<=w*1.2 or
                not .12<pixels/(ww*hh)<.85 or
                ty+hh<y or ty>y+h or protected(tx,ty,ww,hh)):
            continue
        cores.append(idx)
    if not 2<=len(cores)<=len(letters)*3:
        return
    anchor=[idx for idx in cores if stats[idx,0]+a<x+w and stats[idx,0]+a+stats[idx,2]>x]
    if not anchor:
        return
    selected=set(anchor)
    for _ in range(len(cores)):
        for idx in cores:
            xx,yy,ww,hh,_=stats[idx]
            if any(max(0,max(xx,stats[j,0])-min(xx+ww,stats[j,0]+stats[j,2]))<=max(hh,stats[j,3])*.5 and
                   min(yy+hh,stats[j,1]+stats[j,3])-max(yy,stats[j,1])>=min(hh,stats[j,3])*.3 for j in selected):
                selected.add(idx)
    if len(selected)<2:
        return
    left=min(stats[i,0]for i in selected)
    top=min(stats[i,1]for i in selected)
    right=max(stats[i,0]+stats[i,2]for i in selected)
    bottom=max(stats[i,1]+stats[i,3]for i in selected)
    margin=max(2,round(max(stats[i,3]for i in selected)*.1))
    # Отдельные точки и верхние штрихи знака лежат внутри оболочки группы.
    for idx in range(1,count):
        xx,yy,ww,hh,pixels=map(int,stats[idx])
        if (pixels>=8 and left-margin<=xx and xx+ww<=right+margin and
                top-margin<=yy and yy+hh<=bottom+margin and not protected(xx+a,yy+b,ww,hh)):
            selected.add(idx)
    left=min(stats[i,0]for i in selected)
    top=min(stats[i,1]for i in selected)
    right=max(stats[i,0]+stats[i,2]for i in selected)
    bottom=max(stats[i,1]+stats[i,3]for i in selected)
    tx,ty,tw,th=a+int(left),b+int(top),int(right-left),int(bottom-top)
    if ((tw<w*.95 and th<h*.95) or not .5<=tw*th/(w*h)<=4 or max(tw/w,th/h)>3 or protected(tx,ty,tw,th) or
            np.mean(gray[top:bottom,left:right]>180)<.5):
        return
    region.bbox=(tx,ty,tw,th)
    region.auto_layout=None
