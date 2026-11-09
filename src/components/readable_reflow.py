"""Экспериментальные переносы при фиксированном кегле и известной свободной области."""
from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageFont

from src.components.free_text_layout import outline_layer
from src.components.glyph_layout import glyph_mask


def _span(mask, top, bottom):
    """Непрерывный горизонтальный участок, свободный на всей высоте строки."""
    free = np.all(mask[top:bottom] > 0, axis=0)
    edges = np.diff(np.pad(free.astype(int), (1, 1)))
    runs = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
    return max(runs, key=lambda pair: pair[1]-pair[0]) if runs else (0, 0)


def readable_reflow(text, font_path, font_size, allowed, stroke_width=2, *, _measurements=None):
    """Предложить целый текст без уменьшения; None-слой означает нехватку места.

    ``allowed`` уже находится в распрямлённой системе координат строки.
    Это разрешение размещения, а не вывод о безопасности фона изображения.
    Явные переносы здесь допускается перераспределять, слова сохраняются.
    """
    words = text.split()
    mask = np.asarray(allowed)
    if mask.ndim != 2 or max(mask.shape, default=0) > 8192 or not mask.size:
        raise ValueError('Нужна непустая двумерная маска не более 8192 пикселей по стороне')
    if not 1 <= font_size <= 512 or not 0 <= stroke_width <= 64:
        raise ValueError('Кегль или обводка вне допустимого диапазона')
    failure = dict(fits=False, font_size=font_size, lines=[], reason='Недостаточно места при сохранении кегля')
    if not words or len(words) > 100 or len(text) > 2000:
        return None, dict(failure, reason='Пустой или слишком длинный текст')
    font = ImageFont.truetype(str(font_path), font_size)
    pad = math.ceil(stroke_width) + 2
    # Единая высота для всех глифов фразы, включая диакритику и нижние выносы.
    boxes = [font.getbbox(ch) for ch in text if not ch.isspace()]
    glyph_h = max(box[3] for box in boxes)-min(box[1] for box in boxes)
    cell_h = glyph_h + 2*pad
    gap = max(2, round(font_size*.18))
    maximum = min(len(words), 12, (mask.shape[0]+gap)//(cell_h+gap))
    measured = {} if _measurements is None else _measurements

    def measure(start, end):
        key = (start, end)
        if key not in measured:
            phrase = ' '.join(words[start:end])
            # Измеряется тот же безопасный растр глифов, который будет нарисован.
            measured[key] = glyph_mask(phrase, font).size
        return measured[key]

    for count in range(1, maximum+1):
        block_h = count*cell_h+(count-1)*gap
        center = (mask.shape[0]-block_h)//2
        step = max(2, round(font_size/4))
        positions = sorted(set(range(0, mask.shape[0]-block_h+1, step)) | {center, mask.shape[0]-block_h},
                           key=lambda top: (abs(top-center), top))
        seen_spans = set()
        for base_y in positions:
            spans = [_span(mask, base_y+i*(cell_h+gap), base_y+i*(cell_h+gap)+cell_h)
                     for i in range(count)]
            signature = tuple(spans)
            if signature in seen_spans:
                continue
            seen_spans.add(signature)
            if any(right-left <= 2*pad for left, right in spans):
                continue
            states = {(0, 0): (0., [])}
            for row, (left, right) in enumerate(spans):
                width = right-left-2*pad
                for end in range(row+1, len(words)-(count-row-1)+1):
                    options = []
                    for start in range(row, end):
                        previous = states.get((row, start))
                        if previous is None:
                            continue
                        w, h = measure(start, end)
                        if w <= width and h <= glyph_h:
                            options.append((previous[0]+((width-w)/width)**2,
                                            previous[1]+[(start, end)]))
                    if options:
                        states[row+1, end] = min(options, key=lambda value: value[0])
            fitted = states.get((count, len(words)))
            if fitted is None:
                continue
            layer = Image.new('RGBA', (mask.shape[1], mask.shape[0]))
            lines = []
            for row, (start, end) in enumerate(fitted[1]):
                phrase = ' '.join(words[start:end])
                alpha = glyph_mask(phrase, font)
                left, right = spans[row]
                x = (left+right-alpha.width)//2
                y = base_y+row*(cell_h+gap)+(cell_h-alpha.height)//2
                part = Image.new('RGBA', alpha.size, (18, 18, 18, 255))
                part.putalpha(alpha)
                layer.alpha_composite(part, (x, y))
                lines.append(dict(text=phrase, x=int(x), y=int(y)))
            layer = outline_layer(layer, (255, 255, 255), stroke_width)
            if np.any((np.asarray(layer.getchannel('A')) > 0) & (mask == 0)):
                continue
            return layer, dict(fits=True, font_size=font_size, lines=lines, reason='Кегль сохранён')
    return None, failure


def vertical_reflow(text, font_path, font_size, allowed, source_box, stroke_width=2):
    """Расширять поле сначала вниз/вверх, сохраняя ширину, кегль и все слова.

    Маска и рамка заданы в локальных координатах до поворота. Наименьшее
    расширение предпочтительнее; при равной высоте сначала пробуем вниз,
    затем вверх, затем распределяем добавленную высоту на обе стороны.
    Подтверждение безопасности фона должно быть сделано вызывающей стороной.
    """
    mask = np.asarray(allowed)
    if mask.ndim != 2 or not mask.size or max(mask.shape) > 8192:
        raise ValueError('Некорректная маска разрешённой области')
    if (len(source_box) != 4 or any(not isinstance(v, (int, np.integer)) for v in source_box)):
        raise ValueError('Исходная рамка должна содержать четыре целых числа')
    x, y, width, height = map(int, source_box)
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x+width > mask.shape[1] or y+height > mask.shape[0]:
        raise ValueError('Исходная рамка вне маски')
    # Проверка диапазонов общая с базовым подбором, в том числе для отказа.
    measurements = {}
    _, failure = readable_reflow(text, font_path, font_size, mask[y:y+height, x:x+width], stroke_width,
                                 _measurements=measurements)
    font = ImageFont.truetype(str(font_path), font_size)
    pad = math.ceil(stroke_width)+2
    if any(glyph_mask(word, font).width > width-2*pad for word in text.split()):
        return None, dict(failure, fits=False, lines=[], direction='none', growth_up=0, growth_down=0,
                          frame=list(source_box), reason='Целое слово шире исходного поля при сохранении кегля')
    step = max(4, round(font_size/2))
    above, below = y, mask.shape[0]-y-height
    # Границы изображения включаем точно, даже когда они не кратны шагу.
    growths = sorted(set(range(0, above+below+1, step)) | {above, below, above+below})
    seen = set()
    for growth in growths:
        splits = [0, growth]
        splits += sorted(range(max(0, growth-below), min(above, growth)+1, step),
                         key=lambda up: abs(up-growth/2))
        splits += [max(0, growth-below), min(above, growth)]
        for up in splits:
            down = growth-up
            if up > above or down > below or up < 0 or down < 0:
                continue
            top, bottom = y-up, y+height+down
            if (top, bottom) in seen:
                continue
            seen.add((top, bottom))
            layer, fitted = readable_reflow(text, font_path, font_size,
                                            mask[top:bottom, x:x+width], stroke_width,
                                            _measurements=measurements)
            if layer is None:
                continue
            result = Image.new('RGBA', (mask.shape[1], mask.shape[0]))
            result.alpha_composite(layer, (x, top))
            for line in fitted['lines']:
                line['x'] += x
                line['y'] += top
            direction = 'original' if growth == 0 else ('down' if up == 0 else ('up' if down == 0 else 'both'))
            return result, dict(fitted, direction=direction, growth_up=up, growth_down=down,
                                frame=[x, top, width, bottom-top])
    return None, dict(failure, fits=False, lines=[], direction='none', growth_up=0, growth_down=0,
                      frame=list(source_box), reason='Нет места сверху и снизу при сохранении кегля и полного текста')
