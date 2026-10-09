"""Вёрстка перевода в форму баллона или прямоугольник документа."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.components.font_catalog import resolve_font_path, scan_fonts
from src.components.text_warp import warp_image
from src.models import TextRegion, TextStyle
from src.utils.logger import logger
from src.utils.paths import resolve_font

COMIC_FONT = resolve_font("Heroika-Regular.otf")
_HYPHENATORS: dict[str, object] = {}


def _font_file(region: TextRegion) -> Path | None:
    if region.bubble_bbox is not None and COMIC_FONT.exists():
        return COMIC_FONT
    candidates = []
    if region.bubble_bbox is not None:
        candidates.append(Path(r"C:\Windows\Fonts\comic.ttf"))
    candidates.extend([
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ])
    for path in candidates:
        if path.exists():
            return path
    return None


def _load_font(path: Path | None, size: int) -> ImageFont.ImageFont:
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size=size)


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    letter_spacing: float = 0.0,
) -> int:
    """Ширина строки. Нулевой трекинг считается одним вызовом ``textlength``."""
    if not text:
        return 0
    if not letter_spacing:
        return int(draw.textlength(text, font=font))
    width = 0.0
    last = len(text) - 1
    for index, ch in enumerate(text):
        width += float(draw.textlength(ch, font=font))
        if index != last:
            width += letter_spacing
    return int(round(width))


def _line_height(font, size: int) -> int:
    """Высота строки с диакритикой и выносными элементами."""
    try:
        bbox = font.getbbox("ЙАygрд")
        measured = bbox[3] - bbox[1]
    except Exception:
        measured = size
    return max(size, int(measured * 1.15))


def _advance(font, size: int, line_spacing: float = 0.0) -> int:
    """Шаг строки. Нулевой ``line_spacing`` не меняет высоту быстрого пути."""
    line_h = _line_height(font, size)
    if line_spacing:
        return max(1, int(round(line_h + line_spacing)))
    return line_h


def _hyphenator(lang: str):
    code = {
        "ru": "ru_RU",
        "en": "en_US",
        "de": "de_DE",
        "fr": "fr_FR",
        "es": "es_ES",
        "uk": "uk_UA",
    }.get(lang, lang if "_" in lang else "en_US")
    if code in _HYPHENATORS:
        return _HYPHENATORS[code]
    try:
        import pyphen
        dic = pyphen.Pyphen(lang=code)
    except Exception:
        dic = None
    _HYPHENATORS[code] = dic
    return dic


def _split_word(
    word: str,
    font,
    draw,
    max_width: int,
    hyphenator,
    letter_spacing: float = 0.0,
) -> tuple[str, str]:
    if hyphenator is None or len(word) < 4:
        return "", word
    parts = hyphenator.inserted(word).split("-")
    if len(parts) < 2:
        return "", word
    best = ""
    consumed = 0
    best_at = 0
    for index in range(len(parts) - 1):
        consumed += len(parts[index])
        left_letters = sum(ch.isalpha() for ch in word[:consumed])
        right_letters = sum(ch.isalpha() for ch in word[consumed:])
        if left_letters < 3 or right_letters < 3:
            continue
        left = word[:consumed] + "-"
        if _text_width(draw, left, font, letter_spacing) <= max_width:
            best = left
            best_at = consumed
        else:
            break
    if not best:
        return "", word
    return best, word[best_at:]


def _wrap(
    words: list[str],
    font,
    draw,
    max_width: int,
    hyphenator,
    letter_spacing: float = 0.0,
) -> list[str]:
    lines: list[str] = []
    current = ""
    index = 0
    pending = list(words)
    guard = 0
    while index < len(pending) and guard < 400:
        guard += 1
        word = pending[index]
        trial = word if not current else f"{current} {word}"
        if _text_width(draw, trial, font, letter_spacing) <= max_width:
            current = trial
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            continue
        left, rest = _split_word(word, font, draw, max_width, hyphenator, letter_spacing)
        if left and rest:
            lines.append(left)
            pending[index] = rest
            continue
        lines.append(word)
        index += 1
    if current:
        lines.append(current)
    return lines


def _layout_spans(area: np.ndarray, region: TextRegion) -> list[tuple[int, int] | None]:
    """Полосы для раскладки. Крутой поворот сначала кладёт баллон горизонтально."""
    angle = float(getattr(region.style, "rotation", 0) or 0.0)
    if abs(angle) < 15 or not np.any(area):
        return _row_spans(area)
    height, width = area.shape[:2]
    cx = float(region.bbox[0]) + float(region.bbox[2]) / 2.0
    cy = float(region.bbox[1]) + float(region.bbox[3]) / 2.0
    matrix = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0)
    turned = cv2.warpAffine(
        area,
        matrix,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    if not np.any(turned):
        return _row_spans(area)
    return _row_spans(turned)


def _keep_own_ink(overlay: Image.Image, before: np.ndarray, area: np.ndarray) -> Image.Image:
    """Убрать чернила региона, вышедшие за его собственный баллон."""
    arr = np.array(overlay)
    leaked = (arr[..., 3] > before) & (area == 0)
    if not np.any(leaked):
        return overlay
    arr[..., 3] = np.where(leaked, before, arr[..., 3])
    return Image.fromarray(arr)


def _row_spans(mask: np.ndarray) -> list[tuple[int, int] | None]:
    spans = []
    for y in range(mask.shape[0]):
        xs = np.where(mask[y] > 0)[0]
        if xs.size == 0:
            spans.append(None)
        else:
            spans.append((int(xs[0]), int(xs[-1])))
    return spans


def _band_span(spans: list[tuple[int, int] | None], y0: int, y1: int) -> tuple[int, int] | None:
    lefts = []
    rights = []
    for y in range(max(0, y0), min(len(spans), y1)):
        if spans[y] is not None:
            lefts.append(spans[y][0])
            rights.append(spans[y][1])
    if not lefts:
        return None
    left, right = max(lefts), min(rights)
    if right - left < 8:
        return None
    return left, right


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """Залить дыры области по внешнему контуру."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=-1)
    return filled


def interior_mask(image_rgb: np.ndarray, region: TextRegion) -> np.ndarray:
    """Внутренность баллона заливкой от центра текста. Для документа — сам bbox."""
    height, width = image_rgb.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    if region.bubble_bbox is None:
        x, y, box_w, box_h = region.bbox
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + box_w), min(height, y + box_h)
        mask[y0:y1, x0:x1] = 255
        return mask

    bx, by, bw, bh = region.bubble_bbox
    cx = int(region.bbox[0] + region.bbox[2] / 2)
    cy = int(region.bbox[1] + region.bbox[3] / 2)
    cx = min(max(cx, 0), width - 1)
    cy = min(max(cy, 0), height - 1)
    flood_mask = np.zeros((height + 2, width + 2), np.uint8)
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(
        bgr, flood_mask, (cx, cy), (255, 255, 255),
        (20, 20, 20), (20, 20, 20), flags,
    )
    filled = flood_mask[1:-1, 1:-1]
    x0, y0 = max(0, bx), max(0, by)
    x1, y1 = min(width, bx + bw), min(height, by + bh)
    mask[y0:y1, x0:x1] = filled[y0:y1, x0:x1]
    if int(np.sum(mask > 0)) < 80:
        mask[:] = 0
        inset = max(4, min(bw, bh) // 12)
        mask[y0 + inset:max(y0 + inset, y1 - inset), x0 + inset:max(x0 + inset, x1 - inset)] = 255
    mask = _fill_holes(mask)
    if int(np.sum(mask > 0)) > 200:
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=1)
    return mask


def _is_short_reply(text: str) -> bool:
    """Односложные реплики вроде «А», «Да», «Угу» — не раздувать кегль."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    tokens = stripped.split()
    letters = sum(1 for char in stripped if char.isalnum())
    return letters <= 4 or (len(tokens) <= 2 and len(stripped) <= 8)


def _short_reply_cap(
    high: int,
    region: TextRegion,
    regions: list[TextRegion],
    min_font: int,
    interior_h: int,
) -> int:
    """Ограничить потолок кегля медианой соседей или долей высоты баллона."""
    neighbor = [
        int(other.style.font_size or 0)
        for other in regions
        if other.id != region.id
        and other.bubble_bbox is not None
        and int(other.style.font_size or 0) >= min_font
    ]
    if neighbor:
        return min(high, max(min_font, int(round(float(np.median(neighbor)) * 1.15))))
    return min(high, max(min_font, int(round(interior_h * 0.45))))


def layout_inset_px(region: TextRegion, margin_ratio: float) -> int:
    """На сколько сжать внутренность баллона перед раскладкой. 0 — без запаса.

    При включённом запасе держим 2–3 px у края облачка, а не долю короткой стороны.
    """
    if margin_ratio <= 0 or region.bubble_bbox is None or region.block_type == "sfx":
        return 0
    return 3


def inset_layout_mask(area: np.ndarray, inset: int) -> np.ndarray:
    """Сжать маску внутрь. Пустой результат — исходная маска, чтобы мелкий баллон не пропал."""
    if inset <= 0 or not np.any(area):
        return area
    kernel = np.ones((inset * 2 + 1, inset * 2 + 1), np.uint8)
    shrunk = cv2.erode(area, kernel, iterations=1)
    if not np.any(shrunk):
        return area
    return shrunk


def _layout(
    text: str,
    font,
    draw,
    spans,
    hyphenator,
    align: str,
    strict: bool = True,
    letter_spacing: float = 0.0,
    line_spacing: float = 0.0,
    stroke_pad: int = 0,
) -> tuple[list[tuple[str, int, int]], bool]:
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    if not words:
        return [], True
    size = getattr(font, "size", 12)
    line_h = _advance(font, size, line_spacing)
    pad = max(0, int(stroke_pad))
    ys = [index for index, span in enumerate(spans) if span is not None]
    if not ys:
        return [], False
    top, bottom = ys[0], ys[-1] + 1
    limit = bottom - pad
    usable_h = limit - (top + pad)
    mid = (top + bottom) // 2
    center = _band_span(spans, mid - line_h // 2, mid + max(line_h // 2, 1))
    if center is None:
        center = _band_span(spans, top, bottom)
    if center is None:
        return [], False
    lines = _wrap(
        words,
        font,
        draw,
        max(8, center[1] - center[0] - 4 - 2 * pad),
        hyphenator,
        letter_spacing,
    )
    if not lines:
        return [], False
    block_h = len(lines) * line_h
    if (block_h > usable_h or usable_h < line_h) and strict:
        return [], False
    room = max(0, usable_h)
    y = top + pad + max(0, (room - min(block_h, room)) // 2)
    placed: list[tuple[str, int, int]] = []
    for line in lines:
        if y + line_h > limit + 1:
            if strict:
                return [], False
            break
        span = _band_span(spans, y, min(len(spans), y + line_h))
        if span is None:
            if strict:
                return [], False
            break
        width = _text_width(draw, line, font, letter_spacing)
        available = span[1] - span[0] - 4 - 2 * pad
        if width > available + 1 and strict:
            return [], False
        if align == "left":
            x = span[0] + 2
        elif align == "right":
            x = span[1] - 2 - width
        else:
            x = span[0] + max(0, (span[1] - span[0] - width) // 2)
        placed.append((line, x, y))
        y += line_h
    return placed, True


def _background_is_complex(image_rgb: np.ndarray, mask: np.ndarray) -> bool:
    pixels = image_rgb[mask > 0]
    if pixels.shape[0] < 20:
        return False
    return float(pixels.astype(np.float32).std(axis=0).mean()) > 22


def _median_rgb(image_rgb: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    pixels = image_rgb[mask > 0]
    if pixels.size == 0:
        return (255, 255, 255)
    median = np.median(pixels, axis=0)
    return tuple(int(round(float(value))) for value in median)


def _contrast_stroke(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = fill
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    if luminance >= 160:
        return (0, 0, 0)
    return (255, 255, 255)


_LAYER_SCALE = 2
_WARP_KINDS = frozenset({"none", "arc", "ring", "wave", "perspective", "mesh"})


def _style_needs_layer(style: TextStyle) -> bool:
    """Нужен отдельный слой: поворот, скос, трекинг, интерлиньяж или варп."""
    if style.rotation or style.skew_x or style.letter_spacing or style.line_spacing:
        return True
    kind, _bend, _quad, _mesh = _warp_spec(style)
    return kind != "none"


def _warp_spec(style: TextStyle) -> tuple[str, float, list | None, list | None]:
    warp = style.warp if isinstance(style.warp, dict) else {}
    kind = str(warp.get("kind") or "none").strip().lower()
    if kind not in _WARP_KINDS:
        kind = "none"
    try:
        bend = float(warp.get("bend") or 0.0)
    except (TypeError, ValueError):
        bend = 0.0
    quad = warp.get("quad")
    mesh = warp.get("mesh")
    return (
        kind,
        bend,
        quad if isinstance(quad, list) else None,
        mesh if isinstance(mesh, list) else None,
    )


def _scale_points(points, scale: float):
    """Умножить точки квада или сетки на масштаб слоя. Координаты — в пикселях слоя 1×."""
    if not points:
        return None
    scaled = []
    for point in points:
        if isinstance(point, (list, tuple)) and point and isinstance(point[0], (list, tuple)):
            for inner in point:
                if not isinstance(inner, (list, tuple)) or len(inner) < 2:
                    return None
                scaled.append([float(inner[0]) * scale, float(inner[1]) * scale])
            continue
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        scaled.append([float(point[0]) * scale, float(point[1]) * scale])
    return scaled


def _layer_pad(width: int, height: int, stroke: int, style: TextStyle) -> int:
    """Запас вокруг блока, чтобы скос, поворот и дуга не обрезались."""
    pad = max(4, int(stroke) + 2)
    skew = max(-70.0, min(70.0, float(style.skew_x or 0.0)))
    shear = abs(math.tan(math.radians(skew)))
    pad += int(math.ceil(shear * max(height, 1)))
    rad = math.radians(abs(float(style.rotation or 0.0)))
    rot_w = abs(width * math.cos(rad)) + abs(height * math.sin(rad))
    rot_h = abs(width * math.sin(rad)) + abs(height * math.cos(rad))
    pad += int(math.ceil(max(0.0, (rot_w - width) / 2.0 + (rot_h - height) / 2.0)))
    kind, bend, _quad, _mesh = _warp_spec(style)
    amount = abs(bend)
    if kind == "arc" and amount > 0:
        if amount < 0.45:
            pad += int(math.ceil(amount * height / max(0.05, 1.0 - 2.0 * amount))) + 4
        else:
            pad += height * 2
    elif kind == "wave" and amount > 0:
        pad += int(math.ceil(amount * max(width, height) * 0.08)) + 4
    elif kind in ("ring", "perspective", "mesh"):
        pad += int(0.2 * max(width, height)) + 4
    return pad + 2


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font,
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int] | None,
    stroke_width: int,
    letter_spacing: float,
) -> None:
    stroke_fill = (tuple(stroke) + (255,)) if stroke and stroke_width else None
    width = int(stroke_width) if stroke_fill else 0
    color = tuple(int(channel) for channel in fill) + (255,)
    if not letter_spacing:
        draw.text(
            xy,
            text,
            font=font,
            fill=color,
            stroke_width=width,
            stroke_fill=stroke_fill,
        )
        return
    x, y = xy
    last = len(text) - 1
    step = float(letter_spacing)
    for index, ch in enumerate(text):
        draw.text(
            (x, y),
            ch,
            font=font,
            fill=color,
            stroke_width=width,
            stroke_fill=stroke_fill,
        )
        if index != last:
            x += float(draw.textlength(ch, font=font)) + step


def _skew_layer(
    image: Image.Image,
    degrees: float,
    point: tuple[float, float],
) -> tuple[Image.Image, tuple[float, float]]:
    """Скос по X. Второй результат — куда переехала точка ``point``."""
    degrees = max(-70.0, min(70.0, float(degrees)))
    if abs(degrees) < 1e-6:
        return image, point
    shear = math.tan(math.radians(degrees))
    width, height = image.size
    extra = shear * max(height - 1, 0)
    if extra >= 0:
        x_off = 0.0
        new_w = int(math.ceil(width + extra)) + 2
    else:
        x_off = -extra
        new_w = int(math.ceil(width + x_off)) + 2
    transformed = image.transform(
        (max(new_w, 1), height),
        Image.Transform.AFFINE,
        (1.0, -shear, -x_off, 0.0, 1.0, 0.0),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    mapped = (point[0] + x_off + shear * point[1], point[1])
    return transformed, mapped


def _pillow_rotate_matrix(
    width: int,
    height: int,
    degrees: float,
    center: tuple[float, float] | None = None,
) -> tuple[int, int, list[float]]:
    """Обратная матрица Pillow ``rotate(..., expand=True)`` и размер кадра."""
    w = float(width)
    h = float(height)
    pivot = (w / 2.0, h / 2.0) if center is None else (float(center[0]), float(center[1]))
    angle = -math.radians(float(degrees) % 360.0)
    matrix = [
        round(math.cos(angle), 15),
        round(math.sin(angle), 15),
        0.0,
        round(-math.sin(angle), 15),
        round(math.cos(angle), 15),
        0.0,
    ]

    def transform(x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = matrix
        return a * x + b * y + c, d * x + e * y + f

    matrix[2], matrix[5] = transform(-pivot[0], -pivot[1])
    matrix[2] += pivot[0]
    matrix[5] += pivot[1]
    xs: list[float] = []
    ys: list[float] = []
    for x, y in ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h)):
        tx, ty = transform(x, y)
        xs.append(tx)
        ys.append(ty)
    new_w = math.ceil(max(xs)) - math.floor(min(xs))
    new_h = math.ceil(max(ys)) - math.floor(min(ys))
    # Смещение кадра при expand: углы после поворота вокруг pivot.
    min_x = math.floor(min(xs))
    min_y = math.floor(min(ys))
    matrix[2] -= min_x
    matrix[5] -= min_y
    return int(new_w), int(new_h), matrix


def _source_to_dest(matrix: list[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    det = a * e - b * d
    if abs(det) < 1e-12:
        return 0.0, 0.0
    vx = x - c
    vy = y - f
    return (e * vx - b * vy) / det, (-d * vx + a * vy) / det


def _rotate_layer(
    image: Image.Image,
    degrees: float,
    point: tuple[float, float],
    pivot: tuple[float, float] | None = None,
) -> tuple[Image.Image, tuple[float, float]]:
    """Поворот против часовой вокруг ``pivot`` (по умолчанию центр кадра)."""
    if abs(float(degrees)) % 360.0 < 1e-6:
        return image, point
    width, height = image.size
    center = (width / 2.0, height / 2.0) if pivot is None else (float(pivot[0]), float(pivot[1]))
    rotated = image.rotate(
        degrees,
        expand=True,
        center=center,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    _new_w, _new_h, matrix = _pillow_rotate_matrix(width, height, degrees, center=center)
    return rotated, _source_to_dest(matrix, point[0], point[1])


def _paste_rgba(base: Image.Image, layer: Image.Image, xy: tuple[float, float]) -> None:
    x = int(round(xy[0]))
    y = int(round(xy[1]))
    base_w, base_h = base.size
    layer_w, layer_h = layer.size
    if layer_w < 1 or layer_h < 1 or x >= base_w or y >= base_h or x + layer_w <= 0 or y + layer_h <= 0:
        return
    src_x0 = max(0, -x)
    src_y0 = max(0, -y)
    dst_x = max(0, x)
    dst_y = max(0, y)
    src_x1 = min(layer_w, base_w - dst_x + src_x0)
    src_y1 = min(layer_h, base_h - dst_y + src_y0)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return
    cropped = layer.crop((src_x0, src_y0, src_x1, src_y1))
    base.alpha_composite(cropped, dest=(dst_x, dst_y))


def _field_center(region: TextRegion | None, fallback: tuple[float, float]) -> tuple[float, float]:
    """Центр текстового поля (рамки) на странице — общая ось ручки и вёрстки."""
    if region is None:
        return fallback
    box = region.bubble_bbox or region.bbox
    if not box or len(box) < 4:
        return fallback
    x, y, width, height = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    return x + width / 2.0, y + height / 2.0


def _bbox_local_to_layer(
    points: list | None,
    region: TextRegion | None,
    origin_x: float,
    origin_y: float,
    scale: float,
) -> list | None:
    """Точки warp из координат рамки → пиксели слоя (после scale)."""
    if not points or region is None:
        return _scale_points(points, scale) if points else None
    box = region.bbox
    if not box or len(box) < 2:
        return _scale_points(points, scale)
    bx, by = float(box[0]), float(box[1])
    mapped: list[list[float]] = []
    for item in points:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return _scale_points(points, scale)
        page_x = bx + float(item[0])
        page_y = by + float(item[1])
        mapped.append([(page_x - origin_x) * scale, (page_y - origin_y) * scale])
    return mapped


def _composite_styled_layer(
    overlay: Image.Image,
    placed: list[tuple[str, int, int]],
    font,
    font_path: Path | None,
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int] | None,
    stroke_width: int,
    style: TextStyle,
    measure: ImageDraw.ImageDraw,
    region: TextRegion | None = None,
) -> None:
    """Нарисовать блок на слое 2×, скосить, повернуть, поварпить и вклеить в страницу.

    ``quad`` и ``mesh`` в стиле — в координатах рамки региона; перед варпом
    переводятся в пиксели слоя. Поворот — вокруг центра текстового поля.
    """
    scale = _LAYER_SCALE
    size = max(1, int(getattr(font, "size", 12) or 12))
    spacing = float(style.letter_spacing or 0.0)
    line_h = _advance(font, size, float(style.line_spacing or 0.0))
    min_x = min(x for _line, x, _y in placed)
    min_y = min(y for _line, _x, y in placed)
    max_x = max(
        x + _text_width(measure, line, font, spacing) for line, x, _y in placed
    )
    max_y = max(y for _line, _x, y in placed) + line_h
    grow = int(math.ceil(max(0, stroke_width)))
    min_x -= grow
    min_y -= grow
    max_x += grow
    max_y += grow
    box_w = max(1, max_x - min_x)
    box_h = max(1, max_y - min_y)
    pad = _layer_pad(box_w, box_h, stroke_width, style)
    layer_w = (box_w + pad * 2) * scale
    layer_h = (box_h + pad * 2) * scale
    while (layer_w > 4096 or layer_h > 4096) and pad > 2:
        pad = max(2, pad // 2)
        layer_w = (box_w + pad * 2) * scale
        layer_h = (box_h + pad * 2) * scale

    layer = Image.new("RGBA", (max(1, layer_w), max(1, layer_h)), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    font_hi = _load_font(font_path, size * scale)
    stroke_hi = int(stroke_width) * scale if stroke_width else 0
    for line, x, y in placed:
        _draw_tracked(
            layer_draw,
            ((x - min_x + pad) * scale, (y - min_y + pad) * scale),
            line,
            font_hi,
            fill,
            stroke,
            stroke_hi,
            spacing * scale,
        )

    origin_x = float(min_x - pad)
    origin_y = float(min_y - pad)
    glyph_cx = min_x + box_w / 2.0
    glyph_cy = min_y + box_h / 2.0
    world_cx, world_cy = _field_center(region, (glyph_cx, glyph_cy))
    pivot = ((world_cx - origin_x) * scale, (world_cy - origin_y) * scale)
    point = pivot
    if style.skew_x:
        layer, point = _skew_layer(layer, float(style.skew_x), point)
        pivot = point
    if style.rotation:
        layer, point = _rotate_layer(layer, float(style.rotation), point, pivot=pivot)
    kind, bend, quad, mesh = _warp_spec(style)
    if kind != "none":
        layer_quad = _bbox_local_to_layer(quad, region, origin_x, origin_y, scale)
        layer_mesh = _bbox_local_to_layer(mesh, region, origin_x, origin_y, scale)
        if kind == "mesh" and not layer_mesh:
            # Пустая сетка — регулярная решётка по слою, чтобы варп не был no-op.
            lw, lh = layer.size
            layer_mesh = [
                [col * (lw - 1) / 3.0, row * (lh - 1) / 3.0]
                for row in range(4)
                for col in range(4)
            ]
        warped = warp_image(
            np.asarray(layer),
            kind,
            bend=bend,
            quad=layer_quad,
            mesh=layer_mesh,
        )
        layer = Image.fromarray(warped)
        if kind == "arc" and bend:
            # Середина дуги смещается по Y; ведём опорную точку вместе с ней.
            point = (point[0], point[1] - float(bend) * float(layer.size[0]))
    if scale > 1:
        layer = layer.resize(
            (max(1, layer.size[0] // scale), max(1, layer.size[1] // scale)),
            Image.Resampling.LANCZOS,
        )
        point = (point[0] / scale, point[1] / scale)
    _paste_rgba(overlay, layer, (world_cx - point[0], world_cy - point[1]))


def _channel_luminance(value: float) -> float:
    color = max(0.0, min(1.0, value / 255.0))
    if color <= 0.04045:
        return color / 12.92
    return ((color + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    red, green, blue = rgb
    return (
        0.2126 * _channel_luminance(red)
        + 0.7152 * _channel_luminance(green)
        + 0.0722 * _channel_luminance(blue)
    )


def _contrast_ratio(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    lighter = max(_relative_luminance(left), _relative_luminance(right))
    darker = min(_relative_luminance(left), _relative_luminance(right))
    return (lighter + 0.05) / (darker + 0.05)


def _area_color(image_rgb: np.ndarray, area: np.ndarray) -> tuple[int, int, int]:
    """Медиана цвета внутренности баллона на уже очищенной странице."""
    pixels = image_rgb[area > 0]
    if pixels.size == 0:
        return (255, 255, 255)
    median = np.median(pixels, axis=0)
    return tuple(int(channel) for channel in median)


def _readable_fill(
    fill: tuple[int, int, int],
    background: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Чёрный или белый, если заливка почти сливается с фоном баллона."""
    if _contrast_ratio(fill, background) >= 3.0:
        return fill
    black = (0, 0, 0)
    white = (255, 255, 255)
    if _contrast_ratio(white, background) >= _contrast_ratio(black, background):
        return white
    return black


def _fit_size(
    text: str,
    draw,
    spans,
    word_break,
    align: str,
    font_path,
    low: int,
    high: int,
    letter_spacing: float,
    line_spacing: float,
    stroke_pad,
) -> tuple[list | None, ImageFont.ImageFont | None, bool]:
    """Наибольший кегль из ``[low, high]``, который влезает без обрезки."""
    placed = None
    chosen = None
    fits_any = False
    while low <= high:
        mid = (low + high) // 2
        font = _load_font(font_path, mid)
        candidate, fits = _layout(
            text, font, draw, spans, word_break, align,
            letter_spacing=letter_spacing, line_spacing=line_spacing,
            stroke_pad=int(stroke_pad(mid)),
        )
        if fits:
            placed = candidate
            chosen = font
            fits_any = True
            low = mid + 1
        else:
            high = mid - 1
    return placed, chosen, fits_any


class Typesetter:
    """Подбор кегля и перенос по ширине формы на высоте строки."""

    def __init__(
        self,
        min_font_size: int = 10,
        max_font_size: int = 128,
        lang: str = "ru",
        stroke_ratio: float = 0.0,
        user_fonts: str | Path | None = None,
        margin_ratio: float = 0.0,
    ):
        self.min_font_size = min_font_size
        self.max_font_size = max_font_size
        self.lang = lang
        self.stroke_ratio = stroke_ratio
        self.margin_ratio = margin_ratio
        self.user_fonts = Path(user_fonts) if user_fonts else None
        self._font_faces = None

    def _region_font(self, region: TextRegion) -> Path | None:
        """Пустой ``font_id`` оставляет прежний подбор. Иначе — файл из каталога."""
        font_id = str(region.style.font_id or "").strip()
        if not font_id:
            return _font_file(region)
        if self._font_faces is None:
            self._font_faces = scan_fonts(user_dir=self.user_fonts)
        found = resolve_font_path(font_id, self._font_faces)
        if found is not None and found.exists():
            return found
        logger.info(f"Шрифт '{font_id}' не найден, используется запасной")
        return _font_file(region)

    def _stroke_paint(
        self,
        image_rgb: np.ndarray,
        area: np.ndarray,
        region: TextRegion,
        size: int,
    ) -> tuple[tuple[int, int, int] | None, int]:
        """Обводка: auto — как раньше, none — без обводки, custom — цвет и толщина стиля."""
        mode = str(region.style.stroke_mode or "auto").strip().lower()
        if mode not in ("auto", "none", "custom"):
            mode = "auto"
        if mode == "none":
            return None, 0
        if mode == "custom":
            color = region.style.stroke_rgb if region.style.stroke_rgb is not None else (0, 0, 0)
            width = max(1, int(round(float(region.style.stroke_width or 0.0))))
            return color, width
        return self._glyph_stroke(image_rgb, area, region, size)

    def _glyph_stroke(
        self,
        image_rgb: np.ndarray,
        area: np.ndarray,
        region: TextRegion,
        size: int,
    ) -> tuple[tuple[int, int, int] | None, int]:
        """Ореол цвета фона или контрастная обводка на сложном фоне."""
        if self.stroke_ratio <= 0:
            if _background_is_complex(image_rgb, area):
                return region.style.stroke_rgb or (255, 255, 255), max(1, size // 12)
            return None, 0
        if _background_is_complex(image_rgb, area):
            color = region.style.stroke_rgb or _contrast_stroke(region.style.fill_rgb)
            return color, max(2, int(round(size * 0.12)))
        width = max(1, int(round(size * self.stroke_ratio)))
        return _median_rgb(image_rgb, area), width

    def render(
        self,
        image: Image.Image,
        regions: list[TextRegion],
        force: bool = False,
    ) -> tuple[Image.Image, list[int]]:
        """Нарисовать переводы. Второй результат — id регионов, которые не влезли."""
        rgb = np.array(image.convert("RGB"))
        canvas = image.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        hyphenator = _hyphenator(self.lang)
        overflow: list[int] = []
        clip = np.zeros(rgb.shape[:2], dtype=np.uint8)

        for region in regions:
            text = region.translation.strip()
            if not text:
                continue
            if region.style.uppercase:
                text = text.upper()
            area = interior_mask(rgb, region)
            if not np.any(area):
                overflow.append(region.id)
                continue
            clip = np.maximum(clip, area)
            align = "center" if region.bubble_bbox is not None else region.style.alignment
            font_path = self._region_font(region)
            letter_spacing = float(region.style.letter_spacing or 0.0)
            line_spacing = float(region.style.line_spacing or 0.0)
            inset = layout_inset_px(region, self.margin_ratio)
            layout_area = inset_layout_mask(area, inset)
            spans = _layout_spans(layout_area, region)
            placed = None
            chosen_font = None
            override = int(region.style.font_size_override or 0)
            is_sfx = region.block_type == "sfx"
            word_break = None if is_sfx else hyphenator

            def stroke_pad(size: int) -> int:
                _color, width = self._stroke_paint(rgb, area, region, size)
                return int(width or 0)

            if override > 0:
                size = min(self.max_font_size, max(self.min_font_size, override))
                chosen_font = _load_font(font_path, size)
                placed, fits = _layout(
                    text, chosen_font, draw, spans, word_break, align,
                    letter_spacing=letter_spacing, line_spacing=line_spacing,
                    stroke_pad=stroke_pad(size),
                )
                if not fits:
                    overflow.append(region.id)
                    placed = None
                    if force:
                        placed, _ = _layout(
                            text, chosen_font, draw, spans, word_break, align, strict=False,
                            letter_spacing=letter_spacing, line_spacing=line_spacing,
                            stroke_pad=stroke_pad(size),
                        )
            elif is_sfx:
                # Кегль звука — от площади бокса, затем поиск наибольшего влезающего.
                box_w = max(1, int(region.bbox[2]))
                box_h = max(1, int(region.bbox[3]))
                guess = int(round(math.sqrt(box_w * box_h)))
                high = min(self.max_font_size, max(self.min_font_size, guess))
                placed, chosen_font, fits_any = _fit_size(
                    text, draw, spans, None, align, font_path,
                    self.min_font_size, high, letter_spacing, line_spacing, stroke_pad,
                )
                if not fits_any:
                    overflow.append(region.id)
                    placed = None
                    if force:
                        chosen_font = _load_font(font_path, self.min_font_size)
                        placed, _ = _layout(
                            text, chosen_font, draw, spans, None, align, strict=False,
                            letter_spacing=letter_spacing, line_spacing=line_spacing,
                            stroke_pad=stroke_pad(self.min_font_size),
                        )
            elif font_path is None:
                chosen_font = _load_font(None, self.min_font_size)
                placed, fits = _layout(
                    text, chosen_font, draw, spans, hyphenator, align,
                    letter_spacing=letter_spacing, line_spacing=line_spacing,
                    stroke_pad=stroke_pad(self.min_font_size),
                )
                if not fits:
                    overflow.append(region.id)
                    placed = None
            else:
                heights = [index for index, span in enumerate(spans) if span]
                interior_h = (heights[-1] - heights[0] + 1) if heights else self.max_font_size
                high = min(self.max_font_size, max(self.min_font_size, interior_h))
                if _is_short_reply(text) and region.bubble_bbox is not None:
                    high = _short_reply_cap(high, region, regions, self.min_font_size, interior_h)
                placed, chosen_font, fits_any = _fit_size(
                    text, draw, spans, hyphenator, align, font_path,
                    self.min_font_size, high, letter_spacing, line_spacing, stroke_pad,
                )
                if not fits_any:
                    overflow.append(region.id)
                    placed = None
                    if force:
                        chosen_font = _load_font(font_path, self.min_font_size)
                        placed, _ = _layout(
                            text, chosen_font, draw, spans, hyphenator, align, strict=False,
                            letter_spacing=letter_spacing, line_spacing=line_spacing,
                            stroke_pad=stroke_pad(self.min_font_size),
                        )

            if not placed or chosen_font is None:
                continue
            before_alpha = np.array(overlay)[..., 3].copy()
            size = int(getattr(chosen_font, "size", self.min_font_size))
            region.style.font_size = size
            stroke, stroke_width = self._stroke_paint(rgb, area, region, size)
            fill = region.style.fill_rgb
            if region.block_type != "sfx" and not region.style.fill_locked:
                fill = _readable_fill(fill, _area_color(rgb, area))
                region.style.fill_rgb = fill
            if _style_needs_layer(region.style):
                _composite_styled_layer(
                    overlay, placed, chosen_font, font_path, fill, stroke, stroke_width,
                    region.style, draw, region=region,
                )
            else:
                for line, x, y in placed:
                    draw.text(
                        (x, y),
                        line,
                        font=chosen_font,
                        fill=fill + (255,),
                        stroke_width=stroke_width,
                        stroke_fill=(stroke + (255,)) if stroke else None,
                    )
            overlay = _keep_own_ink(overlay, before_alpha, area)
            draw = ImageDraw.Draw(overlay)

        overlay_arr = np.array(overlay)
        overlay_arr[..., 3] = np.where(clip > 0, overlay_arr[..., 3], 0)
        composed = Image.alpha_composite(canvas, Image.fromarray(overlay_arr)).convert("RGB")
        overflow_ids = set(overflow)
        for region in regions:
            region.overflow = region.id in overflow_ids
        if overflow:
            logger.info(f"Typeset overflow: {overflow}")
        return composed, overflow
