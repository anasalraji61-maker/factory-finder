"""Tiny TTL cache (in-memory)."""

import time
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl: float, max_entries: int = 5000, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.max_entries, self._clock = ttl, max_entries, clock
        self._data: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        item = self._data.get(key)
        if item is None:
            return None
        if self._clock() >= item[0]:
            del self._data[key]
            return None
        return item[1]

    def set(self, key: str, value: T) -> None:
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (self._clock() + self.ttl, value)
