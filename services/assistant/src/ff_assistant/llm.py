"""Optional LLM refinement of low-confidence parses (provider-agnostic; never required)."""

from __future__ import annotations

from typing import Any, Protocol

from ff_assistant.config import Settings
from ff_assistant.domain.query import ParsedQuery


class LlmRefiner(Protocol):
    async def refine(self, text: str, parsed: ParsedQuery) -> dict[str, Any] | None: ...


class MockLlm:
    """Deterministic: returns a fixed patch (default none)."""

    def __init__(self, patch: dict[str, Any] | None = None) -> None:
        self.patch = patch

    async def refine(self, text: str, parsed: ParsedQuery) -> dict[str, Any] | None:
        return self.patch


def build_llm(s: Settings) -> LlmRefiner | None:
    # The real provider adapter is intentionally a stub (see docs/decisions/assistant.md).
    return MockLlm() if s.llm_provider == "mock" else None
