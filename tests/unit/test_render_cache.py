from src.app.render_cache import ByteLRU, cache_key


def test_byte_lru_evicts_oldest_and_stays_within_limit():
    cache = ByteLRU(4)
    assert cache.put("a", b"12", 2)
    assert cache.put("b", b"34", 2)
    assert cache.get("a") == b"12"  # a становится самым свежим
    assert cache.put("c", b"56", 2)
    assert cache.get("b") is None
    assert cache.get("a") == b"12"
    assert cache.size_bytes == 4


def test_byte_lru_replaces_clears_and_rejects_oversize():
    cache = ByteLRU(4)
    assert cache.put("x", "old", 2)
    assert cache.put("x", "new", 3)
    assert cache.get("x") == "new"
    assert cache.size_bytes == 3
    assert not cache.put("large", "ignored", 5)
    assert cache.size_bytes == 3
    cache.put("y", "value", 2)
    cache.clear()
    assert cache.get("y") is None
    assert cache.size_bytes == 0


def test_cache_key_is_stable_and_changes_with_inputs():
    assert cache_key({"text": "Привет", "style": {"font": "A"}}) == cache_key(
        {"style": {"font": "A"}, "text": "Привет"}
    )
    assert cache_key({"text": "Привет"}) != cache_key({"text": "Пока"})
