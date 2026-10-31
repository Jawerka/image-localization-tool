"""Сравнение трёх раскладок на одинаковых очищенных страницах и переводах."""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.components import bubble_layout
from src.components import typesetter as current
from src.config import Config
from src.models import TextRegion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-typesetter", type=Path, required=True)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "output/balloon-mask-study/render-candidate",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "output/layout-study")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(
        "baseline_typesetter", args.baseline_typesetter
    )
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    shape = bubble_layout.layout_in_shape
    records = []
    config = Config()
    try:
        for folder in sorted(args.cases.iterdir()):
            if not (folder / "regions.json").exists():
                continue
            data = json.loads((folder / "regions.json").read_text("utf-8"))
            clean = Image.open(folder / "04_clean.jpg").convert("RGB")
            panels = []
            for mode, module in [
                ("legacy", old),
                ("geometry", current),
                ("shape", current),
            ]:
                bubble_layout.layout_in_shape = (
                    current._layout if mode == "geometry" else shape
                )
                regions = [
                    TextRegion.from_dict(r)
                    for r in data["regions"]
                    if r["translation"] and not r["skip"] and r["type"] != "sfx"
                ]
                setter = module.Typesetter(
                    lang="ru",
                    stroke_ratio=config.text_stroke_ratio,
                    margin_ratio=config.text_margin,
                )
                start = time.perf_counter()
                result, overflow = setter.render(clean, regions)
                records.append(
                    {
                        "page": folder.name,
                        "method": mode,
                        "seconds": time.perf_counter() - start,
                        "overflow": overflow,
                        "sizes": {r.id: r.style.font_size for r in regions},
                    }
                )
                if mode == "shape":
                    checks = []
                    rgb = np.array(clean)
                    for r in regions:
                        if not r.bubble_bbox or current._style_needs_layer(r.style):
                            continue
                        area = current.interior_mask(rgb, r)
                        layout_area = current.inset_layout_mask(
                            area, current.layout_inset_px(r, config.text_margin)
                        )
                        font = current._load_font(
                            setter._region_font(r), r.style.font_size
                        )
                        text = (
                            r.translation.upper()
                            if r.style.uppercase
                            else r.translation
                        )
                        _, stroke = setter._stroke_paint(
                            rgb, area, r, r.style.font_size
                        )
                        ink = Image.new("L", clean.size)
                        pen = ImageDraw.Draw(ink)
                        placed, fits = shape(
                            text,
                            font,
                            pen,
                            bubble_layout.shape_row_spans(layout_area),
                            current._hyphenator("ru"),
                            "center",
                            stroke_pad=stroke,
                        )
                        for line, x, y in placed:
                            pen.text(
                                (x, y),
                                line,
                                font=font,
                                fill=255,
                                stroke_width=stroke,
                                stroke_fill=255,
                            )
                        checks.append(
                            {
                                "id": r.id,
                                "fits": fits,
                                "lines": [line for line, _, _ in placed],
                                "outside_layout_pixels": int(
                                    np.count_nonzero(
                                        (np.array(ink) > 0) & (layout_area == 0)
                                    )
                                ),
                            }
                        )
                    records[-1]["checks"] = checks
                result.save(args.output / f"{folder.name}-{mode}.png")
                (args.output / f"{folder.name}-{mode}-regions.json").write_text(
                    json.dumps(
                        [r.to_dict() for r in regions], ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
                thumb = result.copy()
                thumb.thumbnail((900, 900))
                panel = Image.new("RGB", (900, 940), "white")
                panel.paste(thumb, (0, 40))
                ImageDraw.Draw(panel).text((10, 10), mode, fill="black")
                panels.append(panel)
            canvas = Image.new("RGB", (2700, 940), "white")
            for i, panel in enumerate(panels):
                canvas.paste(panel, (i * 900, 0))
            canvas.save(args.output / f"{folder.name}-comparison.jpg", quality=94)
            print(json.dumps(records[-3:]), flush=True)
    finally:
        bubble_layout.layout_in_shape = shape
    (args.output / "metrics.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
