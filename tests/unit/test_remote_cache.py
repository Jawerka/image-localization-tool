"""Кэш PNG на диске: ключ, отпечаток настроек, LRU по байтам."""

import hashlib
import json

from src.app.remote_cache import DEFAULT_MAX_BYTES, CacheKey, ImageCache, fingerprint_settings

_PNG = b"\x89PNG\r\n\x1a\n"


def _blob(size: int, marker: int) -> bytes:
    body = _PNG + bytes([marker % 256]) * size
    return body[:size]


def test_default_max_bytes():
    assert DEFAULT_MAX_BYTES == 512 * 1024 * 1024


def test_cache_key_build_and_token():
    image = _PNG + b"page-a"
    other = _PNG + b"page-b"
    key = CacheKey.build(image, " EN ", " RU ", " fp ")
    assert key.image_sha256 == CacheKey.digest(image)
    assert key.image_sha256 == hashlib.sha256(image).hexdigest()
    assert key.source_lang == "en"
    assert key.target_lang == "ru"
    assert key.fingerprint == "fp"
    raw = f"{key.image_sha256}|ru|fp"
    assert key.token() == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert key.token() == CacheKey.build(image, "en", "ru", "fp").token()
    assert key.token() != CacheKey.build(other, "en", "ru", "fp").token()
    assert key.token() == CacheKey.build(image, "ja", "ru", "fp").token()
    assert key.token() != CacheKey.build(image, "en", "de", "fp").token()
    assert key.token() != CacheKey.build(image, "en", "ru", "other").token()


def test_fingerprint_settings_sorts_keys_and_changes_with_value():
    same = fingerprint_settings({"b": 1, "a": "ё"})
    assert same == fingerprint_settings({"a": "ё", "b": 1})
    payload = json.dumps({"a": "ё", "b": 1}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert same == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert same != fingerprint_settings({"a": "ё", "b": 2})
    assert fingerprint_settings("  Ab ") == "Ab"
    assert fingerprint_settings("   ") == ""
    assert fingerprint_settings(123) == hashlib.sha256(b"123").hexdigest()


def test_put_get_and_miss(tmp_path):
    directory = tmp_path / "cache"
    cache = ImageCache(directory)
    key = CacheKey.build(b"page", "en", "ru", "fp")
    missing = CacheKey.build(b"other", "en", "ru", "fp")
    png = _blob(40, 1)
    assert cache.get(key) is None
    assert not directory.exists()
    cache.put(key, png)
    assert cache.get(key) == png
    assert cache.get(missing) is None
    assert len(cache) == 1
    assert cache.total_bytes == 40
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    entry = index["entries"][key.token()]
    assert entry["size"] == 40
    assert isinstance(entry["last_used"], int)


def test_lru_evicts_oldest_and_get_protects(tmp_path):
    directory = tmp_path / "cache"
    cache = ImageCache(directory, max_bytes=100)
    keys = [CacheKey.build(f"img-{i}".encode(), "en", "ru", "fp") for i in range(4)]
    blobs = [_blob(40, i + 1) for i in range(4)]
    cache.put(keys[0], blobs[0])
    cache.put(keys[1], blobs[1])
    cache.put(keys[2], blobs[2])
    assert cache.get(keys[0]) is None
    assert not (directory / f"{keys[0].token()}.png").exists()
    assert (directory / f"{keys[1].token()}.png").read_bytes() == blobs[1]
    assert (directory / f"{keys[2].token()}.png").read_bytes() == blobs[2]
    assert len(cache) == 2
    assert cache.total_bytes <= 100
    assert cache.get(keys[1]) == blobs[1]
    cache.put(keys[3], blobs[3])
    assert cache.get(keys[1]) == blobs[1]
    assert cache.get(keys[2]) is None
    assert cache.get(keys[3]) == blobs[3]
    assert cache.total_bytes <= 100


def test_oversized_blob_is_not_stored(tmp_path):
    directory = tmp_path / "cache"
    cache = ImageCache(directory, max_bytes=50)
    keep = CacheKey.build(b"keep", "en", "ru", "fp")
    huge_key = CacheKey.build(b"huge", "en", "ru", "fp")
    kept = _blob(40, 1)
    cache.put(keep, kept)
    before = cache.total_bytes
    cache.put(huge_key, _blob(80, 2))
    cache.put(keep, _blob(90, 3))
    assert cache.get(huge_key) is None
    assert cache.get(keep) == kept
    assert len(cache) == 1
    assert cache.total_bytes == before == 40
    fresh = ImageCache(tmp_path / "empty", max_bytes=10)
    fresh.put(CacheKey.build(b"x", "en", "ru", "fp"), _blob(40, 4))
    assert len(fresh) == 0
    assert not (tmp_path / "empty").exists()


def test_reopen_returns_stored_bytes(tmp_path):
    directory = tmp_path / "cache"
    key = CacheKey.build(b"img", "en", "ru", "fp")
    png = _blob(40, 7)
    ImageCache(directory).put(key, png)
    again = ImageCache(directory)
    assert again.get(key) == png
    assert again.total_bytes == 40
    assert len(again) == 1


def test_reopen_keeps_lru_order(tmp_path):
    directory = tmp_path / "cache"
    oldest = CacheKey.build(b"a", "en", "ru", "fp")
    middle = CacheKey.build(b"b", "en", "ru", "fp")
    newest = CacheKey.build(b"c", "en", "ru", "fp")
    first = ImageCache(directory, max_bytes=100)
    first.put(oldest, _blob(40, 1))
    first.put(middle, _blob(40, 2))
    second = ImageCache(directory, max_bytes=100)
    second.put(newest, _blob(40, 3))
    assert second.get(oldest) is None
    assert second.get(middle) == _blob(40, 2)
    assert second.get(newest) == _blob(40, 3)
    assert second.total_bytes <= 100


def test_same_image_hits_changed_fingerprint_misses(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    image = _PNG + b"same"
    fingerprint = fingerprint_settings({"font": "a", "size": 12})
    key = CacheKey.build(image, "en", "ru", fingerprint)
    png = _blob(32, 3)
    cache.put(key, png)
    hit = CacheKey.build(image, "EN", "ru", fingerprint_settings({"size": 12, "font": "a"}))
    assert hit.token() == key.token()
    assert cache.get(hit) == png
    miss = CacheKey.build(image, "en", "ru", fingerprint_settings({"font": "b", "size": 12}))
    assert cache.get(miss) is None


def test_reput_replaces_bytes_and_becomes_newest(tmp_path):
    cache = ImageCache(tmp_path / "cache", max_bytes=100)
    first = CacheKey.build(b"a", "en", "ru", "fp")
    second = CacheKey.build(b"b", "en", "ru", "fp")
    third = CacheKey.build(b"c", "en", "ru", "fp")
    cache.put(first, _blob(40, 1))
    cache.put(second, _blob(40, 2))
    cache.put(first, _blob(40, 9))
    cache.put(third, _blob(40, 3))
    assert cache.get(first) == _blob(40, 9)
    assert cache.get(second) is None
    assert cache.get(third) == _blob(40, 3)
    assert cache.total_bytes <= 100
