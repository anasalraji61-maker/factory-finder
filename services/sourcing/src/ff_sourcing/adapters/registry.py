from __future__ import annotations

from ..config import Settings
from .base import SourceAdapter


class AdapterRegistry:
    def __init__(self, adapters: list[SourceAdapter], enabled: set[str] | None = None):
        self._adapters = {a.id: a for a in adapters}
        self._enabled = (
            set(self._adapters) if enabled is None else set(enabled) & set(self._adapters)
        )

    def all(self) -> list[SourceAdapter]:
        return list(self._adapters.values())

    def enabled(self) -> list[SourceAdapter]:
        return [a for a in self._adapters.values() if a.id in self._enabled]

    def fallback(self) -> SourceAdapter | None:
        """Mock adapter used when a real adapter fails (works even if mock is not enabled)."""
        return self._adapters.get("mock")

    def is_enabled(self, adapter_id: str) -> bool:
        return adapter_id in self._enabled

    def enable(self, adapter_id: str) -> None:
        if adapter_id not in self._adapters:
            raise KeyError(adapter_id)
        self._enabled.add(adapter_id)

    def disable(self, adapter_id: str) -> None:
        self._enabled.discard(adapter_id)


def build_registry(settings: Settings) -> AdapterRegistry:
    from .alibaba import AlibabaAdapter
    from .alibaba_openapi import AlibabaOpenApiAdapter
    from .aliexpress import AliExpressAdapter
    from .made_in_china import MadeInChinaAdapter
    from .mock import MockAdapter
    from .source_1688 import Source1688Adapter

    adapters: list[SourceAdapter] = [
        MockAdapter(),
        AlibabaAdapter(settings),
        AlibabaOpenApiAdapter(),
        MadeInChinaAdapter(settings),
        AliExpressAdapter(settings),
        Source1688Adapter(settings),
    ]
    return AdapterRegistry(adapters, settings.enabled_set())
