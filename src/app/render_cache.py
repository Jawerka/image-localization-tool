"""Потокобезопасный byte-bounded LRU для локального preview."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any


class ByteLRU:
    """Кэш с явным весом значений и строгим верхним пределом памяти."""

    def __init__(self, max_bytes: int):
        self._max_bytes = max(0, int(max_bytes))
        self._items: OrderedDict[str, tuple[Any, int]] = OrderedDict()
        self._size = 0
        self._lock = threading.RLock()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size

    def get(self, key: str):
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item[0]

    def put(self, key: str, value: Any, weight: int) -> bool:
        weight = int(weight)
        if weight < 0:
            return False
        with self._lock:
            if weight > self._max_bytes or self._max_bytes == 0:
                return False
            old = self._items.pop(key, None)
            if old is not None:
                self._size -= old[1]
            self._items[key] = (value, weight)
            self._size += weight
            while self._size > self._max_bytes:
                _old_key, (_old_value, old_weight) = self._items.popitem(last=False)
                self._size -= old_weight
            return True

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._size = 0


def cache_key(payload: dict) -> str:
    """Создать непрозрачный ключ; исходные данные не попадают в логи/отчёты."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
