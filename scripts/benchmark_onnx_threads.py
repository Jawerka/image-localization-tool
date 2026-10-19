#!/usr/bin/env python3
"""Сравнить CPU-потоки ONNX Runtime на локальных страницах."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_pipeline import find_pairs
from src.app.component_catalog import ocr_params
from src.components.bubble_detector import BubbleDetector
from src.components.rapid_ocr import RapidOcr
from src.utils.paths import resolve_model


class RssSampler:
    """Сэмплировать RSS процесса во время одного профиля."""

    def __init__(self):
        self.process = None
        self.peak = 0
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        try:
            import psutil

            self.process = psutil.Process()
            self.started = self.process.memory_info().rss
            self.peak = self.started
            self.thread = threading.Thread(target=self._sample, daemon=True)
            self.thread.start()
        except (ImportError, OSError):
            self.process = None

    def _sample(self):
        while not self.stop.wait(0.02):
            try:
                self.peak = max(self.peak, self.process.memory_info().rss)
            except (OSError, AttributeError):
                return

    def finish(self):
        if self.process is None:
            return {"rss_start_bytes": None, "rss_peak_bytes": None, "rss_end_bytes": None}
        self.stop.set()
        self.thread.join(timeout=1)
        end = self.process.memory_info().rss
        self.peak = max(self.peak, end)
        return {"rss_start_bytes": self.started, "rss_peak_bytes": self.peak, "rss_end_bytes": end}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(np.ceil(fraction * len(ordered))) - 1))
    return round(ordered[index], 4)


def run_profile(thread_count: int, pairs: list[tuple[Path, Path]], repeats: int) -> dict:
    detector = BubbleDetector(
        model_path=resolve_model("ogkalu-detector-v4-s_int8.onnx"),
        intra_op_threads=thread_count,
    )
    ocr = RapidOcr(intra_op_threads=thread_count)
    timings: list[float] = []
    signatures: dict[str, list[str]] = {}
    sampler = RssSampler()
    sampler.start()

    for image_path, _mask_path in pairs:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        # Первый вызов загружает модели; его исключаем из latency.
        detector.detect(image)
        ocr._words(image)
        per_image = []
        for _ in range(repeats):
            started = time.perf_counter()
            found = detector.detect(image)
            words = ocr._words(image)
            per_image.append(time.perf_counter() - started)
            records = [
                f"{item.class_id}:{item.bbox}"
                for item in found
            ]
            records.extend(f"{word.bbox}:{word.text}" for word in words)
            signatures.setdefault(image_path.name, []).append(
                hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
            )
        timings.extend(per_image)

    memory = sampler.finish()
    return {
        "intra_op_threads": thread_count,
        "pages": [path.name for path, _ in pairs],
        "repeats_per_page": repeats,
        "samples": len(timings),
        "latency_median_seconds": round(statistics.median(timings), 4),
        "latency_p95_seconds": percentile(timings, 0.95),
        "throughput_pages_per_minute": round(60 * len(pairs) * repeats / sum(timings), 2),
        "output_signatures": signatures,
        **memory,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=ROOT / "test-img")
    parser.add_argument("--threads", type=int, nargs="+", default=[0, 1, 2, 4, 8])
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--names", type=str, nargs="*", help="Имена страниц для выборочного прогона")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "onnx-thread-benchmark.json")
    args = parser.parse_args()
    if args.pages < 1 or args.repeat < 1 or any(value < 0 or value > 256 for value in args.threads):
        parser.error("threads 0–256, pages и repeat должны быть положительными")

    pairs = find_pairs(args.images)
    if args.names:
        selected = set(args.names)
        pairs = [pair for pair in pairs if pair[0].name in selected]
        missing = selected - {pair[0].name for pair in pairs}
        if missing:
            parser.error(f"Не найдены страницы: {', '.join(sorted(missing))}")
    else:
        pairs = pairs[:args.pages]
    if not pairs:
        parser.error(f"Не найдены пары изображение+маска в {args.images}")
    if not ocr_params():
        parser.error("RapidOCR-компонент не подготовлен")

    report = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "python": sys.version,
        "notes": "0 означает штатный auto; latency включает detector + RapidOCR; первый вызов каждой страницы исключён. Стабильность сравнивает классы/боксы детектора и боксы/текст OCR без confidence.",
        "profiles": [],
    }
    reference = None
    for thread_count in args.threads:
        profile = run_profile(thread_count, pairs, args.repeat)
        stable = reference is None or profile["output_signatures"] == reference
        profile["matches_auto_outputs"] = stable
        if reference is None:
            reference = profile["output_signatures"]
        report["profiles"].append(profile)
        print(
            f"threads={thread_count}: median={profile['latency_median_seconds']:.4f}s "
            f"p95={profile['latency_p95_seconds']:.4f}s "
            f"pages/min={profile['throughput_pages_per_minute']:.2f} "
            f"rss_peak={profile['rss_peak_bytes']} stable={stable}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Отчёт: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
