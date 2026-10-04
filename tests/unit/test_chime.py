"""Десять WAV из extension/src/chime.js: короткие, пик около 0.9."""

from __future__ import annotations

import base64
import json
import shutil
import struct
import subprocess
import wave
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHIME = ROOT / "extension" / "src" / "chime.js"

_NODE = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const context = { console };
vm.createContext(context);
vm.runInContext(code, context);
const api = context.iltChime;
if (!api) throw new Error("iltChime не создан");
const out = api.sounds.map((item) => {
  const bytes = Buffer.from(api.wavBytes(item.id));
  return { id: item.id, title: item.title, b64: bytes.toString("base64") };
});
const fallback = Buffer.from(api.wavBytes("нет такого"));
process.stdout.write(JSON.stringify({
  items: out,
  list: api.list.map((item) => item.id),
  fallback: fallback.toString("base64"),
  defaultId: api.defaultId,
  defaultVolume: api.defaultVolume,
  clamped: api.clampVolume("нет"),
}));
"""


def _load():
    node = shutil.which("node")
    assert node, "node не найден: тест читает chime.js"
    result = subprocess.run(
        [node, "-e", _NODE, str(CHIME)],
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


def _pcm(raw: bytes):
    assert raw[:4] == b"RIFF"
    assert raw[8:12] == b"WAVE"
    with wave.open(BytesIO(raw), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 22050
        frames = handle.readframes(handle.getnframes())
        count = handle.getnframes()
    samples = struct.unpack("<" + "h" * count, frames)
    return count, samples


def test_chimes_are_short_and_quiet():
    data = _load()
    assert len(data["items"]) == 10
    ids = [item["id"] for item in data["items"]]
    assert ids[0] == data["defaultId"] == "drop"
    assert len(set(ids)) == 10
    for item in data["items"]:
        count, samples = _pcm(base64.b64decode(item["b64"]))
        duration = count / 22050
        assert 0.15 <= duration <= 0.5, item["id"]
        peak = max(abs(sample) for sample in samples)
        assert peak > 200, item["id"]
        ratio = peak / 32767
        assert 0.85 <= ratio <= 0.9 + 1e-4, item["id"]
    drop_count, _ = _pcm(base64.b64decode(data["fallback"]))
    first_count, _ = _pcm(base64.b64decode(data["items"][0]["b64"]))
    assert drop_count == first_count
    assert data["defaultVolume"] == 50
    assert data["clamped"] == 50
    assert "off" in data["list"]
    assert "off" not in ids
