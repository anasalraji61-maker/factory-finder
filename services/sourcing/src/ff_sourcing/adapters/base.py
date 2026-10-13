from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..domain.models import ListingDetail, SearchQuery, Supplier


class Health(BaseModel):
    ok: bool
    detail: str = ""


class SourceAdapter(ABC):
    """A supplier-listing source. Real adapters must be lawful per CLAUDE.md rule 6."""

    id: str
    name: str
    mode: str = "mock"  # mock | official_api | licensed_feed
    compliance: str = ""

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        """Return candidate listings. Keyword relevance is applied by the engine."""

    @abstractmethod
    async def get_listing(self, listing_id: str) -> ListingDetail | None: ...

    @abstractmethod
    async def get_supplier(self, supplier_id: str) -> Supplier | None: ...

    @abstractmethod
    async def health(self) -> Health: ...

    def configured(self) -> bool:
        return True
