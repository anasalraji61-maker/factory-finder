"""SignalSource adapters. NO scraping here: real sources must use official APIs/licensed data
(CLAUDE.md rule 6) and be switchable off by config. Humans can also paste posts via
POST /v1/signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RawSignal:
    text: str
    url: str | None = None
    source: str = "mock"
    author: str | None = None  # poster handle: only ever stored as a hash (cooldown / opt-out)
    scraping_disallowed: bool = False  # source robots/ToS forbid automated access -> never ingest


class SignalSource(Protocol):
    async def fetch(self) -> list[RawSignal]: ...


FIXTURES = (
    RawSignal("أحتاج مكائن تعبئة من الصين", "https://example.test/post/1"),
    RawSignal(
        "Looking for filling machines from China, small factory in Basra",
        "https://example.test/post/2",
    ),
    RawSignal("بيع سيارة موديل 2019 بحالة ممتازة", "https://example.test/post/3"),
)


class MockSignalSource:
    async def fetch(self) -> list[RawSignal]:
        return list(FIXTURES)
