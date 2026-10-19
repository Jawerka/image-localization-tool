#!/usr/bin/env python3
"""Прогон пайплайна на локальных страницах: ink recall, spill, время, сравнение картинок.

Эталонные пары лежат локально (не в репозитории): картинка + ``*-mask.*``
с красными прямоугольниками. Путь задаётся ``--images`` / ``--test-dir``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config
from src.page_pipeline import PagePipeline
from src.utils.mask_metrics import (
    cleanup_residue,
    extract_ink_mask,
    ink_recall,
    load_perfect_mask_array,
    spill,
)


class RssSampler:
    """Необязательная выборка RSS процесса во время одного прогона."""

    def __init__(self, interval: float = 0.02):
        self.interval = interval
        self.process = None
        self.started = 0
        self.peak = 0
        self.finished = 0
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        try:
            import psutil

            self.process = psutil.Process()
            self.started = self.process.memory_info().rss
            self.peak = self.started
            self.thread = threading.Thread(target=self._sample, name="ilt-eval-rss", daemon=True)
            self.thread.start()
        except (ImportError, OSError):
            self.process = None

    def _sample(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.peak = max(self.peak, self.process.memory_info().rss)
            except (OSError, AttributeError):
                return

    def stop(self) -> dict:
        if self.process is None:
            return {"rss_start_bytes": None, "rss_peak_bytes": None, "rss_end_bytes": None}
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
        try:
            self.finished = self.process.memory_info().rss
            self.peak = max(self.peak, self.finished)
        except OSError:
            self.finished = 0
        return {"rss_start_bytes": self.started, "rss_peak_bytes": self.peak, "rss_end_bytes": self.finished}


def find_pairs(test_dir: Path) -> list[tuple[Path, Path]]:
    if not test_dir.is_dir():
        return []
    pairs = []
    stems = sorted({path.name.rsplit("-mask", 1)[0] for path in test_dir.glob("*-mask.*")})
    for stem in stems:
        image = next((test_dir / f"{stem}{ext}" for ext in (".jpg", ".png", ".jpeg") if (test_dir / f"{stem}{ext}").exists()), None)
        mask = next((test_dir / f"{stem}-mask{ext}" for ext in (".png", ".jpg", ".jpeg") if (test_dir / f"{stem}-mask{ext}").exists()), None)
        if image and mask:
            pairs.append((image, mask))
    return pairs


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (char_left != char_right)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def cer(hypothesis: str, reference: str) -> float:
    if not reference:
        return 0.0
    return levenshtein(hypothesis, reference) / len(reference)


def load_fixture(stem: str) -> list[str]:
    path = ROOT / "tests" / "fixtures" / f"{stem}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(item) for item in data.get("texts") or []]


def side_by_side(original: Image.Image, mask: np.ndarray, result: Image.Image) -> Image.Image:
    height = original.height
    def fit(image: Image.Image) -> Image.Image:
        if image.height == height:
            return image
        scale = height / image.height
        return image.resize((max(1, int(image.width * scale)), height))

    overlay = original.convert("RGB").copy()
    arr = np.array(overlay)
    red = np.zeros_like(arr)
    red[..., 0] = 255
    hole = mask > 0
    arr[hole] = (0.55 * arr[hole] + 0.45 * red[hole]).astype(np.uint8)
    overlay = Image.fromarray(arr)
    parts = [fit(original.convert("RGB")), fit(overlay), fit(result.convert("RGB"))]
    canvas = Image.new("RGB", (sum(part.width for part in parts), height), "white")
    x = 0
    for part in parts:
        canvas.paste(part, (x, 0))
        x += part.width
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Оценка пайплайна на локальных страницах с эталонными масками"
    )
    parser.add_argument(
        "--images",
        "--test-dir",
        dest="images",
        type=Path,
        default=ROOT / "test-img",
        help="Папка с парами page.ext + page-mask.ext (по умолчанию test-img/)",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "v2")
    parser.add_argument("--ocr", choices=["vlm", "rapid"], default=None)
    parser.add_argument("--translator", choices=["llm", "argos"], default=None)
    parser.add_argument("--inpainter", choices=["lama", "opencv"], default=None)
    parser.add_argument(
        "--rerender",
        action="store_true",
        help="Повторная очистка и вёрстка из output/v2/<stem>/regions.json без LLM",
    )
    parser.add_argument("--repeat", type=int, default=1,
                        help="Повторы rerender в одном pipeline для сравнения первого и тёплого запуска")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat должен быть не меньше 1")
    if args.repeat > 1 and not args.rerender:
        parser.error("Повторы допустимы только с --rerender, чтобы OCR и перевод оставались фиксированными")

    config = Config.load()
    if args.ocr:
        config.ocr_backend = args.ocr
    if args.translator:
        config.translator_backend = args.translator
    if args.inpainter:
        config.inpainter_backend = args.inpainter

    pairs = find_pairs(args.images)
    if not pairs:
        print(
            f"Нет пар изображение+маска в {args.images}. "
            "Положите свои страницы и файлы *-mask.* локально "
            "(папка test-img/ в репозиторий не входит) или укажите --images."
        )
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    for image_path, mask_path in pairs:
        print(f"\n=== {image_path.name} ===")
        debug = args.out / image_path.stem
        pipeline = PagePipeline(config)
        rss = RssSampler()
        rss.start()
        started = time.perf_counter()
        if args.rerender:
            regions_path = debug / "regions.json"
            if not regions_path.exists():
                print(f"  нет {regions_path}")
                return 1
            result = pipeline.rerender(regions_path, debug_dir=debug)
        else:
            result = pipeline.process(
                str(image_path),
                source_lang=config.source_lang,
                target_lang=config.target_lang,
                debug_dir=debug,
            )
        elapsed = time.perf_counter() - started
        destination = args.out / f"{image_path.stem}_result{image_path.suffix}"
        io_started = time.perf_counter()
        result.save(str(destination))
        (args.out / f"{image_path.stem}.regions.json").write_text(
            json.dumps(result.regions_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        output_io_seconds = time.perf_counter() - io_started

        original = Image.open(image_path).convert("RGB")
        perfect = load_perfect_mask_array(mask_path)
        if perfect.shape != (original.height, original.width):
            perfect = np.array(Image.fromarray(perfect).resize(original.size, Image.Resampling.NEAREST))
        predicted = np.array(Image.open(debug / "03_mask.png").convert("L")) if (debug / "03_mask.png").exists() else np.zeros(perfect.shape, np.uint8)
        if predicted.shape != (original.height, original.width):
            predicted = np.array(
                Image.fromarray(predicted).resize(original.size, Image.Resampling.NEAREST)
            )
        original_rgb = np.array(original)
        ink = extract_ink_mask(original_rgb, perfect)
        clean_path = debug / "04_clean.jpg"
        if clean_path.exists():
            cleaned = np.array(Image.open(clean_path).convert("RGB"))
            if cleaned.shape[:2] != original_rgb.shape[:2]:
                cleaned = np.array(
                    Image.fromarray(cleaned).resize(original.size, Image.Resampling.BILINEAR)
                )
            residue_metrics = cleanup_residue(original_rgb, cleaned, perfect)
        else:
            residue_metrics = {"residue": 0.0, "halo": 0.0}
        metrics = {
            "image": image_path.name,
            "run_index": 0,
            "run_kind": "cold_pipeline",
            "seconds": round(elapsed, 2),
            "output_io_seconds": round(output_io_seconds, 4),
            "input_bytes": image_path.stat().st_size,
            "result_bytes": destination.stat().st_size,
            "debug_bytes": sum(path.stat().st_size for path in debug.rglob("*") if path.is_file()),
            "width": original.width,
            "height": original.height,
            "ink_recall": round(ink_recall(predicted, ink), 4),
            "spill": round(spill(predicted, perfect), 4),
            "residue": round(residue_metrics["residue"], 4),
            "halo": round(residue_metrics["halo"], 4),
            "regions": len(result.regions),
            "translated": sum(1 for region in result.regions if region.translation),
            "timings": result.timings,
            "warnings": result.warnings,
            "ocr_engine": result.ocr_engine,
            "translator_engine": result.translator_engine,
        }
        reference = load_fixture(image_path.stem)
        if reference:
            hypothesis = " ".join(region.text for region in sorted(result.regions, key=lambda item: item.order) if region.text)
            reference_text = " ".join(reference)
            metrics["cer"] = round(cer(hypothesis.lower(), reference_text.lower()), 4)
        report.append(metrics)
        comparison = side_by_side(original, predicted, result.output_image)
        compare_started = time.perf_counter()
        comparison.save(args.out / f"{image_path.stem}_compare.jpg", quality=90)
        metrics["output_io_seconds"] = round(
            metrics["output_io_seconds"] + time.perf_counter() - compare_started, 4
        )
        metrics.update(rss.stop())
        metrics["pixel_sha256"] = hashlib.sha256(np.asarray(result.output_image).tobytes()).hexdigest()
        baseline_pixels = np.asarray(result.output_image).copy()
        print(
            f"  ink={metrics['ink_recall']:.1%} spill={metrics['spill']:.1%} "
            f"residue={metrics['residue']:.2%} halo={metrics['halo']:.2%} "
            f"{metrics['seconds']:.1f}s translated={metrics['translated']}"
        )
        for run_index in range(1, args.repeat):
            warm_rss = RssSampler()
            warm_rss.start()
            warm_started = time.perf_counter()
            result = pipeline.rerender(debug / "regions.json", debug_dir=debug)
            warm_seconds = time.perf_counter() - warm_started
            warm_pixels = np.asarray(result.output_image)
            if warm_pixels.shape != baseline_pixels.shape:
                raise RuntimeError(f"Повторный rerender изменил размер: {image_path.name}")
            delta = np.abs(warm_pixels.astype(np.int16) - baseline_pixels.astype(np.int16))
            changed_pixels = int(np.count_nonzero(np.any(delta > 0, axis=2)))
            warm_destination = args.out / f"{image_path.stem}_warm_{run_index + 1}{image_path.suffix}"
            warm_io_started = time.perf_counter()
            result.save(str(warm_destination))
            (args.out / f"{image_path.stem}.regions.json").write_text(
                json.dumps(result.regions_payload(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            output_io_seconds = time.perf_counter() - warm_io_started
            warm_comparison = side_by_side(original, predicted, result.output_image)
            warm_compare_started = time.perf_counter()
            warm_comparison.save(args.out / f"{image_path.stem}_warm_{run_index + 1}_compare.jpg", quality=90)
            output_io_seconds += time.perf_counter() - warm_compare_started
            warm_metrics = dict(metrics)
            warm_predicted = np.array(Image.open(debug / "03_mask.png").convert("L")) if (debug / "03_mask.png").exists() else np.zeros(perfect.shape, np.uint8)
            if warm_predicted.shape[:2] != original_rgb.shape[:2]:
                warm_predicted = np.array(
                    Image.fromarray(warm_predicted).resize(original.size, Image.Resampling.NEAREST)
                )
            warm_clean_path = debug / "04_clean.jpg"
            if warm_clean_path.exists():
                warm_cleaned = np.array(Image.open(warm_clean_path).convert("RGB"))
                if warm_cleaned.shape[:2] != original_rgb.shape[:2]:
                    warm_cleaned = np.array(
                        Image.fromarray(warm_cleaned).resize(original.size, Image.Resampling.BILINEAR)
                    )
                warm_residue_metrics = cleanup_residue(original_rgb, warm_cleaned, perfect)
            else:
                warm_residue_metrics = {"residue": 0.0, "halo": 0.0}
            warm_metrics.update({
                "run_index": run_index,
                "run_kind": "warm_repeat",
                "seconds": round(warm_seconds, 2),
                "output_io_seconds": round(output_io_seconds, 4),
                "timings": result.timings,
                "result_bytes": warm_destination.stat().st_size,
                "pixel_sha256": hashlib.sha256(warm_pixels.tobytes()).hexdigest(),
                "ink_recall": round(ink_recall(warm_predicted, ink), 4),
                "spill": round(spill(warm_predicted, perfect), 4),
                "residue": round(warm_residue_metrics["residue"], 4),
                "halo": round(warm_residue_metrics["halo"], 4),
                "warm_pixel_identical": changed_pixels == 0,
                "changed_pixels": changed_pixels,
                "max_channel_delta": int(delta.max(initial=0)),
            })
            warm_metrics.update(warm_rss.stop())
            report.append(warm_metrics)
            print(
                f"  warm_repeat #{run_index + 1}: {warm_seconds:.2f}s, "
                f"различающихся пикселей {changed_pixels}"
            )

    summary_path = args.out / "eval.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
