"""Сравнение детекторов на эталонах: A ogkalu, B оба, C только второй, D порог 0.15.

Сегментация одна и та же. Отчёт пишет summary.json и index.html.
Режим с языковой моделью помечается как не измеренный, если сервер недоступен.
С языковой моделью сравниваются только A и B и включается поиск пропущенного текста.
Вариант D — контроль порога, в выбор режима не входит.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "mask-eval" / "ab"
VARIANTS = (
    ("A-ogkalu", "ogkalu"),
    ("B-both", "both"),
    ("C-ctd", "ctd"),
    ("D-ogkalu-low", "ogkalu-low"),
)
# С языковой моделью второй детектор может дочитать кроп, порог первого тут ни при чём.
VLM_VARIANTS = (
    ("A-ogkalu", "ogkalu"),
    ("B-both", "both"),
)
# Одиночные режимы, которые могут стать выбором. D остаётся контролем.
SINGLE_CANDIDATES = ("A-ogkalu", "C-ctd")


def _llm_up(base_url: str = "", model: str = "") -> bool:
    sys.path.insert(0, str(ROOT))
    from src.config import Config
    from src.utils.llm_client import LlmClient

    config = Config.load(ROOT / "config.json") if (ROOT / "config.json").is_file() else Config()
    client = LlmClient(
        base_url=(base_url or config.llm_base_url),
        model=(model or config.llm_model),
        timeout=8,
        api_key=getattr(config, "llm_api_key", ""),
    )
    try:
        return bool(client.available())
    except Exception:
        return False


def _run(
    name: str,
    detector: str,
    ocr: str,
    out: Path,
    *,
    llm_url: str = "",
    llm_model: str = "",
    only: list[str] | None = None,
    discover: bool = False,
    ctd_conf: float | None = None,
) -> Path:
    run = f"{name}-{ocr}"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "eval_masks.py"),
        "--images", "test-img",
        "--out", str(out),
        "--run", run,
        "--detector", detector,
        "--ocr", ocr,
    ]
    if llm_url:
        command.extend(["--llm-url", llm_url])
    if llm_model:
        command.extend(["--llm-model", llm_model])
    if only:
        command.append("--only")
        command.extend(only)
    if discover:
        command.append("--discover")
    if ctd_conf is not None:
        command.extend(["--ctd-conf", str(ctd_conf)])
    subprocess.run(command, cwd=ROOT, check=True)
    return out / run / "report.json"


def _page_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _metric(row: dict, key: str):
    return (row.get("metrics") or {}).get(key)


def _measured(summary: dict) -> dict:
    """Оффлайн-таблица, а если её нет — прогон с языковой моделью."""
    offline = summary.get("offline") or {}
    if offline.get("B-both"):
        return offline
    vlm = summary.get("vlm")
    if isinstance(vlm, dict) and vlm.get("B-both"):
        return vlm
    return {}


def _verdict(summary: dict) -> dict:
    """Одна модель, если она не хуже режима «оба» больше чем на 0.5 п. п. и не медленнее.

    Сравнение идёт с парой, а не с лучшей клеткой по всем вариантам.
    Порог 0.15 (D) в выбор не входит: это контроль, не кандидат.
    """
    table = _measured(summary)
    if "B-both" not in table:
        return {"choice": "ogkalu", "reason": "сравнение не собрано", "pages": []}
    pages = sorted({row["name"] for row in table["B-both"] if row.get("metrics")})

    def row_of(name: str, page: str):
        return next((item for item in table.get(name) or [] if item["name"] == page), None)

    def time_of(name: str) -> float:
        total = 0.0
        for row in table.get(name) or []:
            timings = row.get("timings") or {}
            total += float(sum(timings.values()) or 0)
        return total

    both_time = time_of("B-both")
    singles = [name for name in SINGLE_CANDIDATES if table.get(name)]
    chosen = None
    weak_pages: list[str] = []
    for name in singles:
        if both_time and time_of(name) > both_time * 1.02:
            continue
        worse = []
        for page in pages:
            both = row_of("B-both", page)
            row = row_of(name, page)
            if both is None or row is None or not both.get("metrics") or not row.get("metrics"):
                continue
            recall_gap = (_metric(both, "recall") or 0) - (_metric(row, "recall") or 0)
            hit_gap = (_metric(both, "hit6") or 0) - (_metric(row, "hit6") or 0)
            if recall_gap > 0.005 or hit_gap > 0.005:
                worse.append(page)
        if not worse:
            chosen = name
            break
        if not weak_pages or len(worse) < len(weak_pages):
            weak_pages = worse
    if chosen:
        mode = {"A-ogkalu": "ogkalu", "C-ctd": "ctd"}[chosen]
        return {
            "choice": mode,
            "variant": chosen,
            "reason": "одна модель не хуже пары больше чем на 0.5 п. п.",
            "pages": [],
        }
    return {
        "choice": "both",
        "variant": "B-both",
        "reason": "одна модель проигрывает паре больше чем на 0.5 п. п.",
        "pages": weak_pages,
    }


def _html(summary: dict) -> str:
    rows = []
    modes = [key for key in ("offline", "vlm") if isinstance(summary.get(key), dict)]
    pages = []
    for mode in modes:
        for name, items in summary[mode].items():
            for item in items:
                if item["name"] not in pages:
                    pages.append(item["name"])
    header = "".join(f"<th>{mode} {name}</th>" for mode in modes for name in summary[mode])
    for page in pages:
        cells = [f"<td>{page}</td>"]
        for mode in modes:
            for name, items in summary[mode].items():
                row = next((item for item in items if item["name"] == page), None)
                metrics = (row or {}).get("metrics") or {}
                recall = metrics.get("recall")
                hit = metrics.get("hit6")
                proposal = metrics.get("proposal_recall")
                text = "—" if recall is None else f"{recall:.3f} / {hit:.3f}"
                if proposal is not None:
                    text += f"<br>предл. {proposal:.3f}"
                cells.append(f"<td>{text}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    verdict = summary.get("verdict") or {}
    return f"""<!doctype html><meta charset="utf-8"><title>Детекторы</title>
<style>
body {{ font: 14px sans-serif; background: #111; color: #eee; }}
td, th {{ border-bottom: 1px solid #333; padding: 4px 8px; text-align: left; }}
</style>
<p>Покрытие / попадание 6px. {verdict.get("reason", "")} Режим: {verdict.get("choice", "")}.</p>
<table><tr><th>Страница</th>{header}</tr>
{''.join(rows)}
</table>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Сравнение детекторов на эталонах")
    parser.add_argument("--out", default=str(OUT), help="Каталог сводки")
    parser.add_argument("--llm-url", default="", help="Адрес языковой модели")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--only", nargs="*", default=[], help="Имена страниц, как у eval_masks")
    parser.add_argument("--skip-offline", action="store_true", help="Не гонять RapidOCR")
    parser.add_argument("--ctd-conf", type=float, default=None)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    if args.skip_offline and summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary.get("offline"), dict):
            summary["offline"] = {}
    else:
        summary = {"offline": {}, "vlm": "не измерен"}
    if not args.skip_offline:
        for name, detector in VARIANTS:
            path = _run(
                name, detector, "rapid", out,
                only=args.only, ctd_conf=args.ctd_conf,
            )
            summary["offline"][name] = _page_rows(path)
    if _llm_up(args.llm_url, args.llm_model):
        summary["vlm"] = {}
        for name, detector in VLM_VARIANTS:
            path = _run(
                name, detector, "vlm", out,
                llm_url=args.llm_url,
                llm_model=args.llm_model,
                only=args.only,
                discover=True,
                ctd_conf=args.ctd_conf,
            )
            summary["vlm"][name] = _page_rows(path)
    elif "vlm" not in summary:
        summary["vlm"] = "не измерен"
    elif not isinstance(summary.get("vlm"), dict):
        summary["vlm"] = "не измерен"
    summary["verdict"] = _verdict(summary)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "index.html").write_text(_html(summary), encoding="utf-8")
    print(json.dumps(summary["verdict"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
