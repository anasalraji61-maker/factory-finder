"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

Sourcing is keyed by supplier, so the gateway passes the user's *verified* supplier id in ``X-Supplier-Id`` (omitted
when none). Erasure deletes that supplier's native listings and blanks the free text of the user's listing reports.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Header, Request

from ..native_service import NativeService

router = APIRouter(prefix="/v1/internal")
_SUPPLIER_RE = re.compile(r"^sup_[A-Za-z0-9_.:\-]{1,59}$")


def _sup(v: str | None) -> str | None:
    v = (v or "").strip()
    return v if _SUPPLIER_RE.match(v) else None


@router.post("/users/{user_id}/export")
async def export_user(user_id: str, request: Request, x_supplier_id: Annotated[str | None, Header()] = None) -> dict:
    n: NativeService = request.app.state.native
    return {"service": "sourcing", "user_id": user_id, **await n.store.export_user(_sup(x_supplier_id), n.reporter_ref(user_id))}


@router.delete("/users/{user_id}/data")
async def erase_user(user_id: str, request: Request, x_supplier_id: Annotated[str | None, Header()] = None) -> dict:
    n: NativeService = request.app.state.native
    return {"service": "sourcing", "user_id": user_id, "status": "done",
            "counts": await n.store.erase_user(_sup(x_supplier_id), n.reporter_ref(user_id))}  # fmt: skip
