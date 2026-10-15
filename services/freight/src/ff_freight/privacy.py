"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

Erasure anonymizes instead of deleting so counterparties keep their history: ids become a tombstone,
free text is scrubbed, open requests are closed and the user's open quotes withdrawn. Awarded
requests keep their cargo description (needed by the awarded forwarder); ratings keep stars but lose the comment.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from ff_freight.db import (
    applications,
    forwarders,
    quotes,
    rate_events,
    ratings,
    reports,
    shipment_requests,
)

CAP = 500
GONE = "[deleted]"


def tombstone(user_id: str) -> str:
    return "del_" + hashlib.sha256(("ff-freight:" + user_id).encode()).hexdigest()[:16]


def _row(r, keys) -> dict:
    return {k: (r[k].isoformat() if hasattr(r[k], "isoformat") else r[k]) for k in keys}


async def export_user(engine: AsyncEngine, user_id: str) -> dict:
    async with engine.connect() as c:
        apps = (await c.execute(select(applications).where(applications.c.user_id == user_id).limit(CAP + 1))).mappings().all()
        fwd = (await c.execute(select(forwarders).where(forwarders.c.user_id == user_id))).mappings().first()
        reqs = (await c.execute(select(shipment_requests).where(shipment_requests.c.buyer_id == user_id).limit(CAP + 1))).mappings().all()
        qs = (
            (await c.execute(select(quotes).where(quotes.c.forwarder_id == fwd["id"]).limit(CAP + 1))).mappings().all()
            if fwd else []
        )
        rts = (await c.execute(select(ratings).where(ratings.c.buyer_id == user_id).limit(CAP + 1))).mappings().all()
        rps = (await c.execute(select(reports).where(reports.c.reporter_id == user_id).limit(CAP + 1))).mappings().all()
    return {
        "truncated": any(len(x) > CAP for x in (apps, reqs, qs, rts, rps)),
        "data": {
            "applications": [_row(a, ("id", "company_name", "country_code", "description", "lanes", "modes", "incoterms", "status", "created_at")) for a in apps[:CAP]],
            "forwarder": _row(fwd, ("id", "company_name", "country_code", "description", "modes", "incoterms", "status", "created_at")) if fwd else None,
            "shipment_requests": [_row(r, ("id", "origin_country", "origin_place", "destination_country", "destination_place", "cargo_description", "hs_code", "weight_kg", "volume_cbm", "mode", "incoterm", "currency", "status", "created_at")) for r in reqs[:CAP]],
            "quotes": [_row(q, ("id", "request_id", "amount", "currency", "transit_days", "terms", "status", "created_at")) for q in qs[:CAP]],
            "ratings": [_row(r, ("id", "request_id", "stars", "comment", "created_at")) for r in rts[:CAP]],
            "reports": [_row(r, ("target_type", "target_id", "reason", "created_at")) for r in rps[:CAP]],
        },
    }  # fmt: skip


async def erase_user(engine: AsyncEngine, user_id: str) -> dict[str, int]:
    tomb = tombstone(user_id)
    t = datetime.now(UTC)
    n: dict[str, int] = {}
    async with engine.begin() as c:
        r = await c.execute(
            update(applications).where(applications.c.user_id == user_id)
            .values(user_id=tomb, company_name=GONE, description=None, review_note=None)
        )  # fmt: skip
        n["applications_anonymized"] = int(r.rowcount or 0)
        fwd = (await c.execute(select(forwarders.c.id).where(forwarders.c.user_id == user_id))).first()
        if fwd:
            await c.execute(
                update(quotes).where(quotes.c.forwarder_id == fwd.id, quotes.c.status == "submitted")
                .values(status="withdrawn", updated_at=t)
            )  # fmt: skip
            await c.execute(update(quotes).where(quotes.c.forwarder_id == fwd.id).values(terms=None))
            await c.execute(
                update(forwarders).where(forwarders.c.id == fwd.id)
                .values(user_id=tomb, company_name=GONE, description=None, status="suspended", status_reason="account_deleted")
            )  # fmt: skip
        n["forwarders_anonymized"] = 1 if fwd else 0
        await c.execute(
            update(shipment_requests)
            .where(shipment_requests.c.buyer_id == user_id, shipment_requests.c.status == "open")
            .values(status="closed", closed_at=t)
        )  # fmt: skip
        await c.execute(  # not awarded: nothing a counterparty needs, scrub the text
            update(shipment_requests)
            .where(shipment_requests.c.buyer_id == user_id, shipment_requests.c.awarded_quote_id.is_(None))
            .values(cargo_description=GONE, origin_place=GONE, destination_place=GONE)
        )  # fmt: skip
        r = await c.execute(update(shipment_requests).where(shipment_requests.c.buyer_id == user_id).values(buyer_id=tomb))
        n["requests_anonymized"] = int(r.rowcount or 0)
        r = await c.execute(update(ratings).where(ratings.c.buyer_id == user_id).values(buyer_id=tomb, comment=None))
        n["ratings_anonymized"] = int(r.rowcount or 0)
        r = await c.execute(update(reports).where(reports.c.reporter_id == user_id).values(reporter_id=tomb))
        n["reports_anonymized"] = int(r.rowcount or 0)
        await c.execute(delete(rate_events).where(rate_events.c.user_id == user_id))
    return n
