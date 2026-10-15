"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

Trust is keyed by supplier, not by user. The only per-user rows are buyer reports: erasure replaces the reporter id
with a tombstone and keeps the text (abuse evidence, score input). Verification documents/audit are supplier
business records and stay (append-only audit).
"""

import hashlib

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from ff_trust.db import reports

router = APIRouter(prefix="/v1/internal")
CAP = 500


def tombstone(user_id: str) -> str:
    return "del_" + hashlib.sha256(("ff-trust:" + user_id).encode()).hexdigest()[:16]


@router.post("/users/{user_id}/export")
async def export_user(user_id: str, request: Request) -> dict:
    async with request.app.state.db.begin() as c:
        rows = (await c.execute(select(reports).where(reports.c.reporter_id == user_id).limit(CAP + 1))).mappings().all()
    return {
        "service": "trust", "user_id": user_id, "truncated": len(rows) > CAP,
        "data": {"reports": [{"id": r["id"], "supplier_id": r["supplier_id"], "type": r["type"], "text": r["text"],
                              "status": r["status"], "created_at": r["created_at"].isoformat()} for r in rows[:CAP]]},
    }  # fmt: skip


@router.delete("/users/{user_id}/data")
async def erase_user(user_id: str, request: Request) -> dict:
    async with request.app.state.db.begin() as c:
        res = await c.execute(update(reports).where(reports.c.reporter_id == user_id).values(reporter_id=tombstone(user_id)))
    return {"service": "trust", "user_id": user_id, "status": "done", "counts": {"reports_anonymized": int(res.rowcount or 0)},
            "retained": ["verification_documents", "verification_audit"]}  # fmt: skip
