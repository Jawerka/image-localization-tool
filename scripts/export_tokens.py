"""Экспорт ключевых CSS-токенов из web/css/tokens.css в web/tokens.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "web" / "css" / "tokens.css"
OUT_PATH = ROOT / "web" / "tokens.json"

# Имена, нужные Flutter ThemeExtension / chrome metrics.
KEYS = (
    "--ui-scale",
    "--toolbar-h",
    "--pages-w",
    "--inspector-w",
    "--statusbar-h",
    "--btn-h",
    "--icon-size",
    "--radius-control",
    "--radius-sm",
    "--radius-md",
    "--radius-lg",
    "--bg-primary",
    "--bg-secondary",
    "--bg-card",
    "--bg-scene",
    "--surface-1",
    "--surface-2",
    "--surface-3",
    "--primary",
    "--primary-hover",
    "--primary-fg",
    "--accent",
    "--border",
    "--border-strong",
    "--text-primary",
    "--text-muted",
    "--text-success",
    "--text-warning",
    "--text-error",
    "--font-ui",
    "--font-size-ui",
)


def _root_block(text: str) -> str:
    match = re.search(r":root\s*\{([^}]+)\}", text, re.S)
    if not match:
        raise SystemExit("В tokens.css нет блока :root")
    return match.group(1)


def parse_tokens(css: str) -> dict[str, str]:
    block = _root_block(css)
    found: dict[str, str] = {}
    for raw in block.split(";"):
        line = raw.strip()
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if name in KEYS:
            found[name] = value
    missing = [key for key in KEYS if key not in found]
    if missing:
        raise SystemExit(f"Не найдены токены: {', '.join(missing)}")
    return {key: found[key] for key in KEYS}


def main() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    tokens = parse_tokens(css)
    payload = {
        "source": "web/css/tokens.css",
        "tokens": tokens,
    }
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(tokens)} keys)")


if __name__ == "__main__":
    main()
