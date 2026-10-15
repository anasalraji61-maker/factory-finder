"""Publisher adapters. NOTHING in this service calls a publisher automatically: the only caller is
``DemandService.publish_via_adapter`` which needs a named human and an approved, unedited draft.

``RealPublisher`` is OFF by default (``FF_DEMAND_PUBLISHER_ENABLED=false``) and is a stub: a real
channel must use an official API and only ever post PUBLIC replies (never private messages)."""

from __future__ import annotations

from typing import Protocol

from ff_demand.compliance import require_human, sha
from ff_demand.errors import Conflict, Forbidden


def text_sha(text: str) -> str:
    return sha("txt:" + text)


def guard_publish(draft: dict, actor: str) -> None:
    """Refuse unless a human approved exactly this text."""
    require_human(actor)
    if draft.get("status") != "approved":
        raise Conflict("Draft is not approved")
    if not draft.get("approved_by") or not draft.get("approved_at"):
        raise Conflict("Draft has no recorded human approval")
    require_human(draft["approved_by"])
    if draft.get("approved_text_sha") != text_sha(draft.get("text", "")):
        raise Conflict("Draft text changed after approval; re-approve it")


class Publisher(Protocol):
    async def publish(self, draft: dict, actor: str) -> str | None: ...


class MockPublisher:
    """Deterministic, no network. Records what would have been posted."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, draft: dict, actor: str) -> str | None:
        guard_publish(draft, actor)
        self.published.append((draft["id"], actor))
        return f"https://example.test/mock-reply/{draft['id']}"


class RealPublisher:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def publish(self, draft: dict, actor: str) -> str | None:
        if not self.enabled:
            raise Forbidden("Real publisher is disabled", code="publisher_disabled")
        guard_publish(draft, actor)
        raise NotImplementedError("no official channel API is wired; publish by hand")
