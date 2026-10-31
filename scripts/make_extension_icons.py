"""Иконки расширения: скруглённый квадрат и глиф «картинка с облачком реплики».

Пишет PNG 16/32/48/128 в extension/icons. Сборка их только копирует.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "extension" / "icons"
SIZES = (16, 32, 48, 128)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _background(size: int, scale: int) -> Image.Image:
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(canvas * 0.22)
    # Градиент сверху вниз: #3890b5 → #1f5f86.
    for y in range(canvas):
        t = y / max(1, canvas - 1)
        color = (_lerp(0x38, 0x1F, t), _lerp(0x90, 0x5F, t), _lerp(0xB5, 0x86, t), 255)
        draw.line((0, y, canvas, y), fill=color)
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=255)
    image.putalpha(mask)
    return image


def _glyph(size: int, scale: int) -> Image.Image:
    canvas = size * scale
    layer = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    white = (255, 255, 255, 255)
    if size <= 16:
        # Упрощённый знак: рамка и облачко.
        draw.rounded_rectangle((3 * scale, 4 * scale, 10 * scale, 11 * scale), radius=scale, outline=white, width=scale)
        draw.ellipse((8 * scale, 2 * scale, 14 * scale, 7 * scale), outline=white, width=scale)
        return layer
    frame = (int(canvas * 0.16), int(canvas * 0.28), int(canvas * 0.62), int(canvas * 0.72))
    draw.rounded_rectangle(frame, radius=int(canvas * 0.06), outline=white, width=max(1, scale))
    # Горка внутри рамки.
    left, top, right, bottom = frame
    mid = (left + right) // 2
    draw.line((left + scale * 2, bottom - scale * 2, mid, top + scale * 3, right - scale * 2, bottom - scale * 2), fill=white, width=max(1, scale))
    bubble = (int(canvas * 0.48), int(canvas * 0.14), int(canvas * 0.84), int(canvas * 0.42))
    draw.rounded_rectangle(bubble, radius=int(canvas * 0.08), fill=white)
    tail = (
        int(canvas * 0.52), int(canvas * 0.36),
        int(canvas * 0.46), int(canvas * 0.50),
        int(canvas * 0.60), int(canvas * 0.38),
    )
    draw.polygon(tail, fill=white)
    return layer


def render(size: int) -> Image.Image:
    scale = 8 if size <= 32 else 4
    image = _background(size, scale)
    glyph = _glyph(size, scale)
    image.alpha_composite(glyph)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        path = OUT / f"icon{size}.png"
        render(size).save(path, "PNG")


if __name__ == "__main__":
    main()
