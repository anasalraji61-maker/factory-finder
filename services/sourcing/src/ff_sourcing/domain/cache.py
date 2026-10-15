from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(
        self, ttl_s: float = 60.0, maxsize: int = 512, clock: Callable[[], float] = time.monotonic
    ):
        self.ttl_s, self.maxsize, self._clock = ttl_s, maxsize, clock
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any, default: Any = None) -> Any:
        hit = self._data.get(key)
        if hit is None:
            return default
        if hit[0] <= self._clock():
            del self._data[key]
            return default
        return hit[1]

    def set(self, key: Any, value: Any) -> None:
        if len(self._data) >= self.maxsize and key not in self._data:
            now = self._clock()
            for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                del self._data[k]
            if len(self._data) >= self.maxsize:
                del self._data[next(iter(self._data))]
        self._data[key] = (self._clock() + self.ttl_s, value)

    def __len__(self) -> int:
        return len(self._data)


class LRUTTLCache:
    """Size-capped LRU with per-entry TTL. ``ttl_s <= 0`` disables it (get misses, set is a no-op), so callers can
    switch caching off without branching. ``None`` is a valid cached value (use ``MISS`` to detect absence)."""

    MISS: Any = object()

    def __init__(self, ttl_s: float = 60.0, maxsize: int = 256, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.maxsize, self._clock = ttl_s, max(1, maxsize), clock
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def get(self, key: Any) -> Any:
        hit = self._data.get(key)
        if hit is None:
            return self.MISS
        if hit[0] <= self._clock():
            del self._data[key]
            return self.MISS
        self._data.move_to_end(key)
        return hit[1]

    def set(self, key: Any, value: Any) -> None:
        if not self.enabled:
            return
        self._data[key] = (self._clock() + self.ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)  # least recently used

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
