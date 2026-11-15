"""Подтверждение светлых букв внутри уже найденного текстового региона."""

from __future__ import annotations

import cv2
import numpy as np


def fill_flat_dialogue(image, mask, regions):
    """Залить буквы цветного облачка по проверенному свободному фону.

    Кольцо снаружи маски может пересекать контур облачка. Проверяем фон
    внутри текстового поля, а рисунок и градиенты оставляем восстановлению.
    """
    from PIL import Image

    rgb = np.asarray(image.convert('RGB'))
    result = rgb.copy()
    remaining = mask.copy()
    for region in regions:
        if (region.bubble_bbox is None or region.block_type != 'dialogue'
                or region.manual or region.edited):
            continue
        x, y, w, h = region.bbox
        a, b = max(0, x), max(0, y)
        c, d = min(image.width, x+w), min(image.height, y+h)
        crop, hole = rgb[b:d, a:c], remaining[b:d, a:c]
        if not crop.size or not np.any(hole):
            continue
        background = crop[hole == 0]
        if len(background) < max(30, hole.size * .2):
            continue
        colour = np.median(background, axis=0)
        # Только цветные светлые поля: белые облачка уже имеют свой путь.
        if colour.min() < 150 or np.ptp(colour) < 20:
            continue
        distance = np.max(np.abs(background.astype(float)-colour), axis=1)
        if np.percentile(distance, 95) > 12:
            continue
        # Флаг восстановления бывает и у ложных светлых ядер обычной речи.
        # Вместо него проверяем, что под маской лишь тёмные буквы и их
        # сглаживание к тому же фону, а не другая палитра рисунка.
        pixels = crop[hole > 0].astype(float)
        factor = np.clip((pixels @ colour) / (colour @ colour), 0, 1)
        residual = np.max(np.abs(pixels-factor[:, None]*colour), axis=1)
        if np.percentile(residual, 95) > 24:
            continue
        result[b:d, a:c][hole > 0] = np.round(colour).astype(np.uint8)
        hole[:] = 0
    return Image.fromarray(result), remaining


def coherent_colour_ink(crop: np.ndarray, candidate: np.ndarray | None) -> np.ndarray | None:
    """Цветная надпись подтверждается общей палитрой нескольких букв.

    Светлая деталь рисунка внутри изогнутого заголовка не входит в эту
    палитру. Контуры цветных штрихов замыкаются вместе с просветами букв.
    """
    if candidate is None:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    seed = (candidate > 0) & (hsv[..., 1] >= 80)
    if np.count_nonzero(seed) < 40:
        return None
    hue = hsv[..., 0].astype(np.int16)
    counts = np.bincount(hue[seed]//10, minlength=18)
    center = int(np.argmax(counts))*10+5
    delta = np.abs(hue-center)
    match = np.minimum(delta, 180-delta) <= 18
    if np.mean(match[seed]) < .6:
        return None
    saturation = max(80, float(np.percentile(hsv[..., 1][seed], 15))-25)
    binary = (match & (hsv[..., 1] >= saturation)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    height, width = binary.shape
    kept = [i for i in range(1, n) if stats[i, 4] >= 8
            and 3 <= stats[i, 3] <= height*.55 and 2 <= stats[i, 2] <= width*.35
            and stats[i, 0] > 0 and stats[i, 1] > 0
            and stats[i, 0]+stats[i, 2] < width and stats[i, 1]+stats[i, 3] < height]
    if len(kept) < 6:
        return None
    ink = np.isin(labels, kept).astype(np.uint8)*255
    # Небольшой разрыв сглаживания не должен раскрывать контур O/B.
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(ink, contours, -1, 255, -1)
    return ink


def clipped_dark_ink(rgb: np.ndarray, bbox, *, _thick_only: bool = False, include_punctuation: bool = False):
    """Добрать целые буквы белого облачка за тесным боксом детектора.

    Контекст нужен лишь для компонент букв; силуэт и рамка не расширяются.
    """
    x, y, w, h = bbox
    pad = max(8, min(128 if _thick_only else 64, round(min(w, h)*.5)))
    a, b = max(0, x-pad), max(0, y-pad)
    c, d = min(rgb.shape[1], x+w+pad), min(rgb.shape[0], y+h+pad)
    crop = rgb[b:d, a:c]
    if not crop.size or np.mean(np.min(crop, axis=2) >= 240) < .45:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    binary = (gray < 160).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(binary)
    ids = [i for i in range(1, count) if 5 <= stats[i, 4] < w*h*.2
           and 2 <= stats[i, 3] <= h*.95 and 1 <= stats[i, 2] <= w*.6
           and stats[i, 0] > 0 and stats[i, 1] > 0
           and stats[i, 0]+stats[i, 2] < c-a and stats[i, 1]+stats[i, 3] < d-b
           and x-pad*.5 <= a+centers[i, 0] <= x+w+pad*.5
           and y-pad*.5 <= b+centers[i, 1] <= y+h+pad*.5
           and stats[i, 0]+stats[i, 2]+a > x and stats[i, 0]+a < x+w
           and stats[i, 1]+stats[i, 3]+b > y and stats[i, 1]+b < y+h]
    if len(ids) < 3:
        return None
    typical = float(np.median([stats[i, 3] for i in ids]))
    ids = [i for i in ids if stats[i, 3] >= max(3, typical*.35)
           and .12 <= stats[i, 2]/stats[i, 3] <= 8]
    if include_punctuation and not _thick_only:
        margin = max(4, typical*.4)
        ids.extend(i for i in range(1, count) if i not in ids and 5 <= stats[i, 4] <= typical**2*.25
                   and 1 <= stats[i, 2] <= typical*.4 and 2 <= stats[i, 3] <= typical*.85
                   and stats[i, 0] > 0 and stats[i, 1] > 0
                   and stats[i, 0]+stats[i, 2] < c-a and stats[i, 1]+stats[i, 3] < d-b
                   and y <= b+stats[i, 1] and b+stats[i, 1]+stats[i, 3] <= y+h
                   and x-margin <= a+stats[i, 0] and a+stats[i, 0]+stats[i, 2] <= x+w+margin)
    if len(ids) < 3:
        return None
    # Подтверждённая буква может исчезнуть и внутри бокса из-за выбора
    # контрастной маски. Возвращаем компоненты букв, сохраняя фильтр рамки.
    ink = np.zeros_like(gray) if _thick_only else np.isin(labels, ids).astype(np.uint8)*255
    # Буква может касаться тонкой рамки: вся её компонента тогда уходит
    # на край контекста. Отделяем толстое ядро и возвращаем лишь ближний
    # к нему тёмный штрих, не проходя вдоль контура облачка.
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    # Сохраняем прежний добор; более толстое ядро отдельно отделяет букву
    # от рамки на увеличенных страницах. Оно может пересекать тесный бокс,
    # даже когда центр буквы остался за его краем.
    cutoffs = sorted({4.0, max(4.0, typical*.04)}) if _thick_only else [3.0]
    for cutoff in cutoffs:
        cores = (distance > cutoff).astype(np.uint8)
        n_core, core_labels, core_stats, core_centers = cv2.connectedComponentsWithStats(cores)
        margin = pad*.5 if cutoff > 3 else 0
        joined = [i for i in range(1, n_core) if core_stats[i, 4] >= 10
                  and max(4, typical*.35) <= core_stats[i, 3] <= h*.65
                  and (cutoff == 3 or core_stats[i, 3] <= typical*1.8)
                  and 2 <= core_stats[i, 2] <= w*.6
                  and (cutoff == 3 or core_stats[i, 2]/core_stats[i, 3] >= .2)
                  and core_stats[i, 0] > 0 and core_stats[i, 1] > 0
                  and core_stats[i, 0]+core_stats[i, 2] < c-a and core_stats[i, 1]+core_stats[i, 3] < d-b
                  and x-margin <= a+core_centers[i, 0] <= x+w+margin
                  and y-margin <= b+core_centers[i, 1] <= y+h+margin
                  and a+core_stats[i, 0]+core_stats[i, 2] > x
                  and a+core_stats[i, 0] < x+w
                  and b+core_stats[i, 1]+core_stats[i, 3] > y
                  and b+core_stats[i, 1] < y+h
                  and (_thick_only or not np.any(np.isin(labels[core_labels == i], ids)))]
        if joined:
            reached = np.isin(core_labels, joined).astype(np.uint8)
            for _ in range(max(3, int(np.ceil(cutoff)))):
                reached = cv2.dilate(reached, np.ones((3, 3), np.uint8)) & binary
            ink = np.maximum(ink, reached*255)
    if not _thick_only:
        extra = clipped_dark_ink(rgb, bbox, _thick_only=True)
        if extra is not None:
            addition, (aa, bb, cc, dd) = extra
            addition[b-bb:d-bb, a-aa:c-aa] = np.maximum(
                addition[b-bb:d-bb, a-aa:c-aa], ink)
            return addition, (aa, bb, cc, dd)
    if not np.any(ink):
        return None
    return ink, (a, b, c, d)


def contrasted_dark_ink(crop: np.ndarray) -> np.ndarray | None:
    """Тёмные буквы на неоднородной полупрозрачной плашке.

    Локальное замыкание оценивает фон под узким штрихом, а не берёт
    единый цвет из кольца. На ровной бумаге прежний путь не меняется.
    """
    if crop.ndim != 3 or min(crop.shape[:2]) < 16:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    median = float(np.median(gray))
    if not 100 <= median < 225 or np.mean(np.min(crop, axis=2) >= 245) > .5:
        return None
    radius = max(3, min(31, round(height * .09)))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1)))
    contrast = background.astype(np.int16) - gray.astype(np.int16)
    peaks = ((contrast >= 28) & (gray < median-20)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(peaks)
    ids = [i for i in range(1, count) if 8 <= stats[i, 4] <= gray.size*.06
           and 3 <= stats[i, 3] <= height*.6 and 2 <= stats[i, 2] <= width*.25
           and stats[i, 0] > 0 and stats[i, 1] > 0
           and stats[i, 0]+stats[i, 2] < width and stats[i, 1]+stats[i, 3] < height]
    if len(ids) < 6:
        return None
    typical = float(np.percentile([stats[i, 3] for i in ids], 65))
    ids = [i for i in ids if typical*.35 <= stats[i, 3] <= typical*1.8]
    ink = np.isin(labels, ids).astype(np.uint8)*255
    if len(ids) < 6 or not .008 <= np.mean(ink > 0) <= .35:
        return None
    clear = cv2.dilate((ink > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) == 0
    if np.count_nonzero(clear) < 50:
        return None
    lo, hi = np.percentile(crop[clear], [10, 90], axis=0)
    if np.max(hi-lo) < 30:
        return None
    return ink


def confirmed_light_ink(crop: np.ndarray) -> tuple[np.ndarray | None, bool]:
    """Сохранить белые буквы и дополнить их подтверждёнными цветными ядрами."""
    original, inverse = _confirmed_light_ink(crop)
    halo = _pastel_letter_halo(crop)
    if halo is not None:
        original = halo if original is None else np.maximum(original, halo)
        inverse = True
    if crop.ndim != 3 or min(crop.shape[:2]) < 8:
        return original, inverse
    chroma = np.ptp(crop, axis=2)
    tinted = (np.min(crop, axis=2) >= 180) & (chroma >= 30) & (chroma < 80)
    if np.count_nonzero(tinted) < 6:
        return original, inverse
    addition, outlined = _confirmed_light_ink(crop, include_tinted=True)
    if addition is None:
        return original, inverse
    return (addition if original is None else np.maximum(original, addition)), inverse or outlined


def _pastel_letter_halo(crop: np.ndarray) -> np.ndarray | None:
    """Широкая пастельная обводка вокруг нескольких светлых букв.

    Тёплые полупрозрачные ядра тоже считаются светлыми. Цветное поле
    отбрасывается, если оно не образует ограниченную оболочку ядер.
    """
    if crop.ndim != 3 or min(crop.shape[:2]) < 16:
        return None
    cores = (crop.min(2) >= 150) & (crop.max(2) >= 190) & (np.ptp(crop, axis=2) < 80)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cores.astype(np.uint8))
    height, width = cores.shape
    ids = [i for i in range(1, n) if stats[i, 4] >= 12 and min(stats[i, 2:4]) >= 3
           and 8 <= stats[i, 3] < height*.85 and stats[i, 2] < width*.7
           and stats[i, 4] < cores.size*.15 and stats[i, 0] > 0 and stats[i, 1] > 0
           and stats[i, 0]+stats[i, 2] < width and stats[i, 1]+stats[i, 3] < height]
    if len(ids) < 3:
        return None
    typical = float(np.percentile(stats[ids, 3], 75))
    ids = [i for i in ids if stats[i, 3] >= typical*.35]
    if len(ids) < 3:
        return None
    cores = np.isin(labels, ids)
    ring = (cv2.dilate(cores.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~cores
    chroma = np.ptp(crop, axis=2) > 18
    pixels = crop[ring & chroma]
    if len(pixels) < max(20, np.count_nonzero(ring)*.6):
        return None
    colours, counts = np.unique(pixels.astype(np.int32)//16, axis=0, return_counts=True)
    if counts.max() < len(pixels)*.25:
        return None
    dominant = colours[counts.argmax()]
    colour = np.median(pixels[np.all(pixels.astype(np.int32)//16 == dominant, axis=1)], axis=0)
    delta = crop.astype(np.float32)-crop.mean(axis=2, keepdims=True)
    direction = colour-colour.mean()
    # Оттенок оболочки сохраняется при просвечивании разного фона.
    # Более бледное синее поле не должно присоединяться к бирюзовым буквам.
    projection = np.sum(delta*direction, axis=2)/max(1., float(np.sum(direction**2)))
    shell = ((np.linalg.norm(crop.astype(np.float32)-colour, axis=2) < 65)
             & chroma & (projection >= .85))
    distance = cv2.distanceTransform((~cores).astype(np.uint8), cv2.DIST_L2, 5)
    local = shell & (distance <= typical*.4)
    # Если тот же цвет продолжается далеко за буквы, это заливка плашки.
    near = (distance > typical*.4) & (distance < typical*.7)
    if np.any(near) and np.mean(shell[near]) > .35:
        return None
    if np.count_nonzero(local) < np.count_nonzero(cores)*.4:
        return None
    result = (local | cores).astype(np.uint8)*255
    contours, _ = cv2.findContours(result, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return cv2.drawContours(result, contours, -1, 255, -1)


def _confirmed_light_ink(crop: np.ndarray, *, include_tinted: bool = False) -> tuple[np.ndarray | None, bool]:
    """Светлые штрихи на контрастном фоне либо светлое ядро с обводкой.

    Большие светлые поля и рамки отбрасываются. Возвращается маска чернил
    до отступа ретуши и признак включённой в неё обводки.
    """
    if crop.ndim != 3 or min(crop.shape[:2]) < 8:
        return None, False
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    neutral = np.ptp(crop, axis=2) < 45
    white = (np.min(crop, axis=2) >= 210) & neutral
    coloured = _colour_outline(crop)
    # Просветы обычных чёрных букв на бумаге тоже окружены чёрным:
    # преобладающее белое поле не является белой сердцевиной наклейки.
    # Цветная оболочка на таком поле всё же ищется отдельно.
    if float(np.mean(white)) > .5:
        return (coloured, True) if coloured is not None else (None, False)
    dark_panel = float(np.percentile(gray, 50)) < 120 and float(np.percentile(gray, 70)) < 170
    faded = _faded_light_ink(crop, gray) if dark_panel else None
    if not dark_panel:
        enclosed = _inverse_outline(gray, white)
        if enclosed is not None:
            return np.maximum(enclosed, coloured) if coloured is not None else enclosed, True
    # Светлые сиреневые/голубые ядра подтверждаются тёмным кольцом ниже.
    # Они дополняют прежний порог, не меняя проверку белого поля/просветов.
    chroma = np.ptp(crop, axis=2)
    tinted = include_tinted & (np.min(crop, axis=2) >= 180) & (chroma >= 30) & (chroma < 80)
    bright = (((np.min(crop, axis=2) >= (180 if dark_panel else 210)) & neutral)
              | tinted).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    seeds = np.zeros_like(gray)
    outlined_seeds = np.zeros_like(gray)
    accepted = 0
    sizes = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < 3 or min(w, h) < 2 or area > gray.size * .20:
            continue
        if x == 0 or y == 0 or x + w == width or y + h == height:
            continue
        if w > width * .9 or h > height * .9:
            continue
        body = labels[y:y+h, x:x+w] == index
        if not dark_panel:
            ya, xa = max(0, y-3), max(0, x-3)
            yb, xb = min(height, y+h+3), min(width, x+w+3)
            local = (labels[ya:yb, xa:xb] == index).astype(np.uint8)
            ring = (cv2.dilate(local, kernel) > 0) & (local == 0)
            if not np.any(ring):
                continue
            surround = gray[ya:yb, xa:xb][ring]
            core = float(np.median(gray[y:y+h, x:x+w][body]))
            if np.mean(surround < core - 28) < .60:
                continue
            # Цветное облачко не является чёрной обводкой: расширение
            # по тёмным пикселям допускается только для подтверждённой оболочки.
            if np.mean(surround < 100) >= .60:
                outlined_seeds[y:y+h, x:x+w][body] = 255
        else:
            # На тёмной панели одной абсолютной темноты недостаточно:
            # обводка должна быть темнее самого фона за узким кольцом.
            ya, xa = max(0, y-6), max(0, x-6)
            yb, xb = min(height, y+h+6), min(width, x+w+6)
            local = (labels[ya:yb, xa:xb] == index).astype(np.uint8)
            near = cv2.dilate(local, np.ones((5, 5), np.uint8)) > 0
            far = cv2.dilate(local, np.ones((13, 13), np.uint8)) > 0
            ring = near & (local == 0)
            context = far & ~near
            patch = gray[ya:yb, xa:xb]
            if np.any(context) and np.any(ring):
                if np.mean(patch[ring] < float(np.median(patch[context]))-12) >= .30:
                    outlined_seeds[y:y+h, x:x+w][body] = 255
        seeds[y:y+h, x:x+w][body] = 255
        accepted += 1
        sizes.append(min(w, h))
    if accepted < 2 or np.mean(seeds > 0) > .35:
        extra = faded if coloured is None else coloured if faded is None else np.maximum(faded, coloured)
        return (extra, True) if extra is not None else (None, False)
    if not np.any(outlined_seeds):
        if faded is not None:
            seeds = np.maximum(seeds, faded)
            return (np.maximum(seeds, coloured) if coloured is not None else seeds), True
        return (np.maximum(seeds, coloured), True) if coloured is not None else (seeds, False)
    # От белого ядра до внешней границы тёмной обводки. Фон и другие
    # несвязанные чёрные объекты не входят в геодезическое расширение.
    if dark_panel:
        # Общая оболочка подтверждена контрастными буквами строки.
        # На соседней букве фон может совпасть с оттенком края; она должна
        # получить тот же ограниченный запас, а не оставить контур для LaMa.
        outlined_seeds = seeds
    reached = outlined_seeds > 0
    dark = gray < 135
    steps = min(10, max(3, round(float(np.median(sizes)) * .65)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _ in range(steps):
        expanded = (cv2.dilate(reached.astype(np.uint8), kernel) > 0) & dark
        reached |= expanded
    result = np.maximum(seeds, reached.astype(np.uint8) * 255)
    if faded is not None:
        result = np.maximum(result, faded)
    return np.maximum(result, coloured) if coloured is not None else result, True


def _faded_light_ink(crop: np.ndarray, gray: np.ndarray) -> np.ndarray | None:
    """Приглушённые светлые буквы подтверждаются локальным контрастом ядра.

    Дополнение предназначено только для тёмных регионов без белых букв.
    Несколько отдельных ядер должны иметь тёмное окружение; рост оболочки
    ограничен толщиной штриха, чтобы не уйти по связанному рисунку.
    """
    if np.percentile(gray, 99) >= 205:
        return None
    size = max(9, min(31, round(min(gray.shape)*.12))) | 1
    opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    peaks = ((gray.astype(np.int16)-opened >= 16)
             & (gray >= max(100, float(np.percentile(gray, 95))-25))
             & (np.ptp(crop, axis=2) < 55))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(peaks.astype(np.uint8))
    seeds = np.zeros_like(gray)
    widths = []
    for idx in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[idx])
        if area < 6 or min(w, h) < 2 or w > gray.shape[1]*.4 or h > gray.shape[0]*.8:
            continue
        if x == 0 or y == 0 or x+w == gray.shape[1] or y+h == gray.shape[0]:
            continue
        xa, ya = max(0, x-2), max(0, y-2)
        xb, yb = min(gray.shape[1], x+w+2), min(gray.shape[0], y+h+2)
        body = (labels[ya:yb, xa:xb] == idx).astype(np.uint8)
        ring = (cv2.dilate(body, np.ones((5, 5), np.uint8)) > 0) & (body == 0)
        patch = gray[ya:yb, xa:xb]
        core = float(np.median(patch[body > 0]))
        if not np.any(ring) or np.mean(patch[ring] < core-22) < .55:
            continue
        seeds[ya:yb, xa:xb][body > 0] = 255
        widths.append(min(w, h))
    if len(widths) < 5 or not .008 < np.mean(seeds > 0) < .30:
        return None
    radius = max(2, min(8, round(float(np.median(widths))*.45)))
    return cv2.dilate(seeds, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1)))


def _letter_like_cores(cores: np.ndarray) -> int:
    """Число светлых ядер, похожих на отдельные буквы, а не на плашку."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(cores.astype(np.uint8))
    letters = 0
    height, width = cores.shape
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < 8 or min(w, h) < 2 or area > cores.size * .20:
            continue
        if w > width * .9 or h > height * .9:
            continue
        letters += 1
    return letters


def _close_shell_near_cores(cores: np.ndarray, shell: np.ndarray) -> np.ndarray | None:
    """Соединить цветную оболочку только вокруг ядер, не заливая баллон."""
    ys, xs = np.where(cores)
    if len(xs) < 8:
        return None
    hull = cv2.convexHull(np.column_stack((xs, ys)).astype(np.int32))
    neighborhood = np.zeros(cores.shape, np.uint8)
    cv2.fillConvexPoly(neighborhood, hull, 255)
    neighborhood = cv2.dilate(neighborhood, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    local = ((shell > 0) & (neighborhood > 0)).astype(np.uint8) * 255
    if np.count_nonzero(local) > np.count_nonzero(cores) * 6:
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(local, cv2.MORPH_CLOSE, kernel)
    closed[neighborhood == 0] = 0
    return closed


def _chroma_peak_shell(crop: np.ndarray) -> np.ndarray:
    """Оболочка как локальный пик насыщенности относительно медианы поля."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    chroma = np.ptp(crop, axis=2).astype(np.float32)
    med_sat = float(np.median(sat))
    med_chroma = float(np.median(chroma))
    peak = (sat > med_sat + 32) | (chroma > med_chroma + 22)
    peak &= (sat > med_sat + 18) & (chroma > max(28.0, med_chroma + 12))
    neigh = cv2.blur(sat, (15, 15))
    peak &= sat > neigh + 10
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(peak.astype(np.uint8), cv2.MORPH_CLOSE, kernel) > 0


def _colour_outline(crop: np.ndarray) -> np.ndarray | None:
    """Замкнутая цветная обводка светлых букв, подтверждённая их ядрами.

    Цвет выбирается из кольца самих букв. Сплошная цветная плашка
    отбрасывается по выходу на границу и отношению оболочки к ядру.
    Если «ядра» покрывают поле, оболочка — локальный пик хромы.
    На тёмной текстуре пик хромы дополняет глобальное кольцо: второй
    оттенок обводки не обязан попасть в dist < 38 к яркому цвету.
    """
    cores = ((np.min(crop, axis=2) >= 170) & (np.max(crop, axis=2) >= 200)
             & (np.ptp(crop, axis=2) < 65))
    field = float(np.mean(cores)) > .35
    if field:
        cores = np.zeros(cores.shape, bool)
        shell = _chroma_peak_shell(crop)
        letter_cores = 0
    else:
        chroma = np.ptp(crop, axis=2) > 35
        ring = (cv2.dilate(cores.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~cores
        pixels = crop[ring & chroma]
        if len(pixels) < 20:
            return None
        colours, counts = np.unique(pixels.astype(np.int32) // 16, axis=0, return_counts=True)
        if counts.max() < len(pixels) * .12:
            return None
        colour = colours[counts.argmax()] * 16 + 8
        colour_match = (np.linalg.norm(crop.astype(np.float32) - colour, axis=2) < 38) & chroma
        # Второй оттенок той же обводки (тень на волосах) дальше глобального
        # dist < 38; локальный пик хромы дополняет кольцо, не ослабляя порог.
        shell = colour_match | _chroma_peak_shell(crop)
        letter_cores = _letter_like_cores(cores)
        if letter_cores:
            closed = _close_shell_near_cores(cores, shell)
            if closed is not None:
                shell = shell | (closed > 0)
    if not np.any(shell):
        return None
    union = shell if field else (cores | shell)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(union.astype(np.uint8))
    result = np.zeros(shell.shape, np.uint8)
    accepted = 0
    height, width = shell.shape
    for idx in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[idx])
        body = labels[y:y+h, x:x+w] == idx
        if field:
            if area < 16 or min(w, h) < 3 or area > shell.size * .20:
                continue
            if w > width * .85 or h > height * .85:
                continue
            if area / max(1, w * h) > .70:
                continue
        else:
            core = cores[y:y+h, x:x+w] & body
            size = np.count_nonzero(core)
            if size < 8 or not size * 1.2 <= area <= size * 6 or area > cores.size * .55:
                continue
            touches_edge = x == 0 or y == 0 or x + w == width or y + h == height
            if touches_edge:
                rows, cols = np.where(core)
                if not len(cols):
                    continue
                gx, gy = x + cols, y + rows
                if gx.min() == 0 or gy.min() == 0 or gx.max() == width - 1 or gy.max() == height - 1:
                    continue
        contours, _ = cv2.findContours(body.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = cv2.drawContours(np.zeros((h, w), np.uint8), contours, -1, 255, -1)
        result[y:y+h, x:x+w] = np.maximum(result[y:y+h, x:x+w], filled)
        accepted += 1
    if accepted >= 2 or (accepted >= 1 and letter_cores >= 2):
        return result
    return None


def _inverse_outline(gray: np.ndarray, white: np.ndarray) -> np.ndarray | None:
    """Замкнутая тёмная оболочка с белым ядром, включая сплошные I и L."""
    height, width = gray.shape
    dark = (gray < 120).astype(np.uint8)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = np.zeros_like(gray)
    letters = 0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 3 or x == 0 or y == 0 or x+w == width or y+h == height:
            continue
        if w*h > gray.size * .3:
            continue
        local = np.zeros((h, w), np.uint8)
        cv2.drawContours(local, [contour - (x, y)], -1, 255, -1)
        body = local > 0
        light = white[y:y+h, x:x+w] & body
        if np.count_nonzero(light) < 4 or not .08 < np.mean(light[body]) < .85:
            continue
        result[y:y+h, x:x+w] = np.maximum(result[y:y+h, x:x+w], local)
        letters += 1
    return result if letters >= 2 else None


def preserves_picture(crop: np.ndarray) -> bool:
    """Светлая плашка с рисунком/градиентом не является непрозрачной бумагой."""
    if not crop.size:
        return False
    # JPEG-ореолы вокруг плотного текста дают разброс светлых пикселей,
    # хотя большую часть непрозрачной бумаги составляет чистый белый фон.
    if np.mean(np.min(crop, axis=2) >= 250) > .5:
        return False
    # Отступ от тёмных штрихов исключает их сглаживание из оценки фона.
    # В прозрачной плашке и после отступа остаются разные оттенки рисунка.
    clear = cv2.erode((np.min(crop, axis=2) > 180).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    light = crop[clear].astype(np.float32)
    if len(light) < 12:
        return False
    lo, hi = np.percentile(light, [10, 90], axis=0)
    return bool(np.max(hi - lo) > 8)


def smooth_line_mask(crop: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Плотные обведённые строки на размытом фоне закрываются целиком.

    На детальном рисунке остаётся точная маска: прямоугольник строки там
    удалил бы лишние линии. Светлая оболочка/тёмное ядро сюда не направляются.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    exclude = cv2.dilate((ink > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    background = np.hypot(gx, gy)[~exclude]
    if background.size < 50 or np.percentile(background, 90) > 8:
        return ink
    # Белые сердцевины разделяют строки даже там, где их чёрные обводки
    # соприкасаются. По внешним контурам получался один прямоугольник абзаца.
    cores = (gray >= 230) & (ink > 0)
    counts = np.sum(cores, axis=1)
    rows = np.flatnonzero(counts >= max(5, gray.shape[1] * .012))
    if not len(rows):
        return ink
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 2) + 1)
    groups = [group for group in groups if len(group) >= 5]
    if len(groups) < 2:
        return ink
    result = ink.copy()
    for group in groups:
        y0, y1 = int(group[0]), int(group[-1]) + 1
        xs = np.flatnonzero(np.any(ink[y0:y1] > 0, axis=0))
        if y1-y0 < 5 or len(xs) < 5:
            continue
        pad = max(1, min(6, round((y1-y0) * .12)))
        result[max(0, y0-pad):min(gray.shape[0], y1+pad), xs[0]:xs[-1]+1] = 255
    return result


def smooth_light_mask(crop: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """На гладком фоне скрыть также просветы между светлыми буквами.

    Узкие дырки оставляли в контексте восстановления цветные тени исходных
    штрихов. Оболочка надписи убирает этот контекст, не заполняя всё облачко.
    Детальный рисунок и резкие границы за пределами букв не расширяются.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    exclude = cv2.dilate((ink > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    background = np.hypot(gx, gy)[~exclude]
    if background.size < 50 or np.percentile(background, 90) > 8:
        return ink
    ys, xs = np.where(ink > 0)
    if len(xs) < 12:
        return ink
    hull = cv2.convexHull(np.column_stack((xs, ys)).astype(np.int32))
    result = np.zeros_like(ink)
    cv2.fillConvexPoly(result, hull, 255)
    return result


def boundary_ink(image, bbox, bounds):
    """Восстановить только подтверждённые компоненты, обрезанные краем ROI."""
    x, y, w, h = bbox
    pad = max(8, min(64, round(min(w, h) * .25)))
    a, b, c, d = bounds
    aa, bb, cc, dd = max(0, x-pad), max(0, y-pad), min(image.width, x+w+pad), min(image.height, y+h+pad)
    if (aa, bb, cc, dd) == bounds:
        return None
    extra, inverse = confirmed_light_ink(np.asarray(image.crop((aa, bb, cc, dd))))
    if extra is None or not inverse:
        return None
    _, labels, stats, _ = cv2.connectedComponentsWithStats((extra > 0).astype(np.uint8))
    inside = np.zeros_like(extra, bool)
    inside[b-bb:d-bb, a-aa:c-aa] = True
    crossing = np.intersect1d(np.unique(labels[inside]), np.unique(labels[~inside]))
    crossing = crossing[crossing > 0]
    # Добор относится к букве/слову у края, а не к большому фрагменту
    # облачка или рисунка, связавшемуся со светлой обводкой.
    crossing = [i for i in crossing if stats[i, 4] <= w*h*.2
                and stats[i, 2] <= w*.75 and stats[i, 3] <= h*.75
                and stats[i, 0] > 0 and stats[i, 1] > 0
                and stats[i, 0]+stats[i, 2] < cc-aa and stats[i, 1]+stats[i, 3] < dd-bb]
    if not len(crossing):
        return None
    extra = np.isin(labels, crossing).astype(np.uint8) * 255
    extra = cv2.dilate(extra, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return extra, (aa, bb, cc, dd)
