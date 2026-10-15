"""Business logic. Every public method is one request; counters change in the same transaction."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from sqlalchemy import and_, delete, exists, func, insert, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ff_freight import cursor as cur
from ff_freight.config import Settings
from ff_freight.db import (
    applications,
    forwarder_lanes,
    forwarders,
    now,
    quotes,
    rate_events,
    ratings,
    reports,
    shipment_requests,
)
from ff_freight.errors import Conflict, Forbidden, Invalid, NotFound, RateLimited
from ff_freight.moderation import redact, screen_fields
from ff_freight.ranking import Candidate, normalise_weights, rank
from ff_freight.schemas import (
    ApplicationCreate,
    ProfileUpdate,
    QuoteCreate,
    RatingIn,
    RequestCreate,
    csv_key,
    csv_list,
)

R = shipment_requests
Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
MAX_READY_DAYS = 365
FORMULA = (
    "score = 100 x (w_price x cheapest/price + w_transit x fastest/transit + w_rating x adjusted_rating/5); "
    "adjusted_rating = (sum of stars + 3 x 2) / (rating count + 2)"
)


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond:06d}Z"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _money(d: Decimal) -> str:
    return format(d.quantize(Q2, ROUND_HALF_UP), "f")


def _wt(d: Decimal | None) -> str | None:
    return None if d is None else format(d.quantize(Q3, ROUND_HALF_UP), "f")


def _f(d: Decimal) -> float:
    return float(d)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


class FreightService:
    def __init__(self, engine: AsyncEngine, settings: Settings, clock: Callable[[], datetime] = now):
        self.engine, self.s, self.clock = engine, settings, clock

    # ------------------------------------------------------------------ helpers
    async def create_all(self) -> None:
        from ff_freight.db import metadata

        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    def _limit(self, limit: int | None) -> int:
        return max(1, min(limit or self.s.default_page_size, self.s.max_page_size))

    async def _rate(self, user: str, action: str) -> None:
        """Rolling-window limit stored in the DB (holds across replicas). Attempts later rejected by
        screening count too, so the banned-term list cannot be probed."""
        limit = getattr(self.s, f"rate_{action}")
        if limit == 0:
            return
        t = self.clock()
        window = timedelta(seconds=self.s.rate_window_seconds)
        where = and_(rate_events.c.user_id == user, rate_events.c.action == action)
        async with self.engine.begin() as c:
            await c.execute(delete(rate_events).where(where, rate_events.c.created_at < t - window))
            rows = (
                await c.execute(
                    select(rate_events.c.created_at).where(where).order_by(rate_events.c.created_at).limit(limit)
                )
            ).all()
            if len(rows) >= limit:
                wait = max(1, math.ceil((rows[0][0] + window - t).total_seconds()))
                raise RateLimited(
                    "Too many requests, slow down",
                    code="rate_limited",
                    details={"action": action, "limit": limit, "retry_after_seconds": wait},
                    headers={"Retry-After": str(wait)},
                )
            await c.execute(insert(rate_events).values(user_id=user, action=action, created_at=t))

    @staticmethod
    def _screen(fields: dict[str, str | None]) -> None:
        flags = screen_fields(fields)
        if flags:
            reasons = sorted({f.message for f in flags})[:4]
            raise Invalid(
                "Content not allowed: remove contact details, links and prohibited items",
                code="content_rejected",
                details={"reasons": reasons},
            )

    def _page_of(self, rows, limit: int, mapper) -> dict:
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = cur.encode("c", rows[-1].created_at, rows[-1].id) if more and rows else None
        return {"items": [mapper(r) for r in rows], "next_cursor": nxt}

    @staticmethod
    def _after_time(q, cursor: str | None, table):
        """Newest-first keyset: rows strictly older than (created_at, id) of the cursor."""
        if cursor:
            d = cur.decode(cursor, ("c",))
            q = q.where(
                or_(
                    table.c.created_at < d["t"],
                    and_(table.c.created_at == d["t"], table.c.id < d["i"]),
                )
            )
        return q.order_by(table.c.created_at.desc(), table.c.id.desc())

    async def _expire(self, c) -> int:
        """Auto expiry: open requests past their deadline become 'expired' (idempotent, indexed)."""
        t = self.clock()
        res = await c.execute(
            update(R).where(R.c.status == "open", R.c.expires_at <= t).values(status="expired", closed_at=t)
        )
        return res.rowcount or 0

    # ------------------------------------------------------------------ serializers
    @staticmethod
    def _lane_list(rows) -> list[dict]:
        return [{"origin_country": r.origin_country, "destination_country": r.destination_country} for r in rows]

    async def _lanes(self, c, fids: list[str]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {f: [] for f in fids}
        if fids:
            rows = await c.execute(
                select(forwarder_lanes)
                .where(forwarder_lanes.c.forwarder_id.in_(fids))
                .order_by(forwarder_lanes.c.origin_country, forwarder_lanes.c.destination_country)
            )
            for r in rows:
                out[r.forwarder_id].append(
                    {"origin_country": r.origin_country, "destination_country": r.destination_country}
                )
        return out

    @staticmethod
    def _rating(r) -> dict:
        avg = None
        if r.rating_count:
            avg = format((Decimal(r.rating_sum) / Decimal(r.rating_count)).quantize(Q2, ROUND_HALF_UP), "f")
        return {"average": avg, "count": r.rating_count}

    def _forwarder(self, r, lanes: list[dict], *, private: bool = False, admin: bool = False) -> dict:
        d = {
            "id": r.id,
            "company_name": r.company_name,
            "country_code": r.country_code,
            "description": r.description,
            "lanes": lanes,
            "modes": csv_list(r.modes),
            "incoterms": csv_list(r.incoterms),
            "certifications": r.certifications,
            "rating": self._rating(r),
            "completed_jobs": r.completed_count,
            "verified_at": _iso(r.verified_at),
            "created_at": _iso(r.created_at),
        }
        if private or admin:
            d["status"] = r.status
        if admin:
            d |= {"user_id": r.user_id, "status_reason": r.status_reason}
        return d

    @staticmethod
    def _summary(r) -> dict:
        avg = None
        if r.rating_count:
            avg = format((Decimal(r.rating_sum) / Decimal(r.rating_count)).quantize(Q2, ROUND_HALF_UP), "f")
        return {
            "id": r.id,
            "company_name": r.company_name,
            "country_code": r.country_code,
            "rating": {"average": avg, "count": r.rating_count},
            "completed_jobs": r.completed_count,
        }

    @staticmethod
    def _application(r, admin: bool = False) -> dict:
        d = {
            "id": r.id,
            "company_name": r.company_name,
            "country_code": r.country_code,
            "description": r.description,
            "lanes": [{"origin_country": o, "destination_country": x} for o, x in r.lanes],
            "modes": csv_list(r.modes),
            "incoterms": csv_list(r.incoterms),
            "certifications": r.certifications,
            "status": r.status,
            "review_note": r.review_note,
            "forwarder_id": r.forwarder_id,
            "created_at": _iso(r.created_at),
            "reviewed_at": _iso(r.reviewed_at),
        }
        if admin:
            d["user_id"] = r.user_id
        return d

    @staticmethod
    def _request(r, view: str) -> dict:
        """view: owner | winner | forwarder | admin."""
        priv = view in ("owner", "winner", "admin")
        d = {
            "id": r.id,
            "origin_country": r.origin_country,
            "origin_place": r.origin_place,
            "destination_country": r.destination_country,
            "destination_place": r.destination_place,
            "cargo_description": r.cargo_description,
            "hs_code": r.hs_code,
            "weight_kg": r.weight_kg,
            "volume_cbm": r.volume_cbm,
            "mode": r.mode,
            "container_type": r.container_type,
            "container_count": r.container_count,
            "incoterm": r.incoterm,
            "ready_date": r.ready_date.isoformat(),
            "currency": r.currency,
            "landed_cost_ref": r.landed_cost_ref,
            "status": r.status,
            "outcome": (("completed" if r.awarded_quote_id else "cancelled") if r.status == "closed" else None),
            "quote_count": r.quote_count,
            "expires_at": _iso(r.expires_at),
            "awarded_at": _iso(r.awarded_at) if priv else None,
            "awarded_quote_id": r.awarded_quote_id if priv else None,
            "buyer_id": r.buyer_id if priv else None,
            "closed_at": _iso(r.closed_at),
            "created_at": _iso(r.created_at),
        }
        if view == "admin":
            d |= {
                "visibility": r.visibility,
                "hidden_reason": r.hidden_reason,
                "report_count": r.report_count,
                "awarded_forwarder_id": r.awarded_forwarder_id,
            }
        return d

    def _quote(self, r, fwd=None, admin: bool = False) -> dict:
        t = self.clock()
        d = {
            "id": r.id,
            "request_id": r.request_id,
            "forwarder_id": r.forwarder_id,
            "amount": r.amount,
            "currency": r.currency,
            "transit_days": r.transit_days,
            "valid_until": _iso(r.valid_until),
            "valid": r.status == "submitted" and r.valid_until > t,
            "inclusions": r.inclusions,
            "exclusions": r.exclusions,
            "breakdown": r.breakdown,
            "terms": r.terms,
            "status": r.status,
            "revision": r.revision,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
        }
        if fwd is not None:
            d["forwarder"] = self._summary(fwd)
        if admin:
            d |= {"visibility": r.visibility, "hidden_reason": r.hidden_reason, "report_count": r.report_count}
        return d

    # ------------------------------------------------------------------ identity
    async def _forwarder_of(self, c, user: str):
        return (await c.execute(select(forwarders).where(forwarders.c.user_id == user))).first()

    async def _require_forwarder(self, c, user: str, *, active: bool = True):
        f = await self._forwarder_of(c, user)
        if f is None:
            raise Forbidden("An approved forwarder account is required", code="forwarder_required")
        if active and f.status != "active":
            raise Forbidden("This forwarder account is suspended", code="forwarder_suspended")
        return f

    async def whoami(self, user: str) -> dict:
        async with self.engine.connect() as c:
            f = await self._forwarder_of(c, user)
        return {"user_id": user, "forwarder_id": f.id if f else None, "forwarder_status": f.status if f else None}

    # ------------------------------------------------------------------ applications (claim flow)
    async def apply(self, user: str, body: ApplicationCreate) -> dict:
        async with self.engine.connect() as c:
            if await self._forwarder_of(c, user):
                raise Conflict("This account is already an approved forwarder", code="already_forwarder")
            pending = await c.scalar(
                select(func.count()).select_from(applications).where(
                    applications.c.user_id == user, applications.c.status == "pending"
                )
            )
            total = await c.scalar(
                select(func.count()).select_from(applications).where(applications.c.user_id == user)
            )
        if pending:
            raise Conflict("An application is already pending review", code="application_pending")
        if (total or 0) >= self.s.max_applications_per_user:
            raise Conflict("Application limit reached; contact support", code="application_limit_reached")
        if len(body.lanes) > self.s.max_lanes_per_forwarder:
            raise Invalid("Too many lanes", code="lane_limit_exceeded")
        await self._rate(user, "applications")
        self._screen(
            {
                "company_name": body.company_name,
                "description": body.description,
                "certifications": " ; ".join(body.certifications),
            }
        )
        aid, t = _new_id("app"), self.clock()
        async with self.engine.begin() as c:
            await c.execute(
                insert(applications).values(
                    id=aid, user_id=user, company_name=body.company_name, country_code=body.country_code,
                    description=body.description,
                    lanes=[[x.origin_country, x.destination_country] for x in body.lanes],
                    modes=csv_key(body.modes), incoterms=csv_key(body.incoterms),
                    certifications=body.certifications, status="pending", created_at=t,
                )  # fmt: skip
            )
            r = (await c.execute(select(applications).where(applications.c.id == aid))).one()
        return self._application(r)

    async def my_applications(self, user: str) -> dict:
        async with self.engine.connect() as c:
            rows = (
                await c.execute(
                    select(applications)
                    .where(applications.c.user_id == user)
                    .order_by(applications.c.created_at.desc(), applications.c.id.desc())
                    .limit(self.s.max_applications_per_user)
                )
            ).all()
        return {"items": [self._application(r) for r in rows], "next_cursor": None}

    # ------------------------------------------------------------------ forwarder profiles
    async def my_profile(self, user: str) -> dict:
        async with self.engine.connect() as c:
            f = await self._require_forwarder(c, user, active=False)
            lanes = (await self._lanes(c, [f.id]))[f.id]
        return self._forwarder(f, lanes, private=True)

    async def update_profile(self, user: str, body: ProfileUpdate) -> dict:
        changes = body.model_dump(exclude_unset=True)
        if "lanes" in changes and changes["lanes"] is None:
            raise Invalid("lanes cannot be null", code="validation_error")
        if body.lanes and len(body.lanes) > self.s.max_lanes_per_forwarder:
            raise Invalid("Too many lanes", code="lane_limit_exceeded")
        for k in ("modes", "incoterms"):
            if k in changes and changes[k] is None:
                raise Invalid(f"{k} cannot be null", code="validation_error")
        self._screen(
            {
                "description": body.description,
                "certifications": " ; ".join(body.certifications or []),
            }
        )
        async with self.engine.begin() as c:
            f = await self._require_forwarder(c, user, active=False)
            vals: dict = {}
            if "description" in changes:
                vals["description"] = body.description
            if "modes" in changes:
                vals["modes"] = csv_key(body.modes)  # type: ignore[arg-type]
            if "incoterms" in changes:
                vals["incoterms"] = csv_key(body.incoterms)  # type: ignore[arg-type]
            if "certifications" in changes:
                vals["certifications"] = body.certifications or []
            if vals:
                await c.execute(update(forwarders).where(forwarders.c.id == f.id).values(**vals))
            if body.lanes is not None:
                await c.execute(delete(forwarder_lanes).where(forwarder_lanes.c.forwarder_id == f.id))
                await c.execute(
                    insert(forwarder_lanes),
                    [
                        {"forwarder_id": f.id, "origin_country": x.origin_country,
                         "destination_country": x.destination_country}
                        for x in body.lanes
                    ],
                )  # fmt: skip
            f = (await c.execute(select(forwarders).where(forwarders.c.id == f.id))).one()
            lanes = (await self._lanes(c, [f.id]))[f.id]
        return self._forwarder(f, lanes, private=True)

    async def get_forwarder(self, user: str, fid: str) -> dict:
        async with self.engine.connect() as c:
            f = (await c.execute(select(forwarders).where(forwarders.c.id == fid))).first()
            if f is None or (f.status != "active" and f.user_id != user):
                raise NotFound("Forwarder not found")
            lanes = (await self._lanes(c, [fid]))[fid]
        return self._forwarder(f, lanes, private=f.user_id == user)

    async def list_forwarders(
        self, origin: str | None, destination: str | None, mode: str | None, incoterm: str | None,
        cursor: str | None, limit: int | None,
    ) -> dict:  # fmt: skip
        limit = self._limit(limit)
        q = select(forwarders).where(forwarders.c.status == "active")
        if origin or destination:
            conds = []
            if origin:
                conds.append(forwarder_lanes.c.origin_country.in_((origin, "*")))
            if destination:
                conds.append(forwarder_lanes.c.destination_country.in_((destination, "*")))
            q = q.where(
                exists().where(forwarder_lanes.c.forwarder_id == forwarders.c.id, *conds)
            )
        if mode:
            q = q.where(forwarders.c.modes.like(f"%,{mode},%"))
        if incoterm:
            q = q.where(forwarders.c.incoterms.like(f"%,{incoterm},%"))
        q = self._after_time(q, cursor, forwarders)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
            lanes = await self._lanes(c, [r.id for r in rows[:limit]])
        page = self._page_of(rows, limit, lambda r: self._forwarder(r, lanes[r.id]))
        return page

    async def forwarder_ratings(self, fid: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        async with self.engine.connect() as c:
            f = (await c.execute(select(forwarders.c.status).where(forwarders.c.id == fid))).first()
            if f is None or f.status != "active":
                raise NotFound("Forwarder not found")
            q = self._after_time(select(ratings).where(ratings.c.forwarder_id == fid), cursor, ratings)
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, self._rating_row)

    @staticmethod
    def _rating_row(r) -> dict:
        return {"id": r.id, "request_id": r.request_id, "forwarder_id": r.forwarder_id, "stars": r.stars,
                "comment": r.comment, "created_at": _iso(r.created_at)}  # fmt: skip

    # ------------------------------------------------------------------ requests
    def _lane_match(self, lanes: list[dict]):
        conds = []
        for ln in lanes:
            o, d = ln["origin_country"], ln["destination_country"]
            if o == "*" and d == "*":
                return true()
            parts = []
            if o != "*":
                parts.append(R.c.origin_country == o)
            if d != "*":
                parts.append(R.c.destination_country == d)
            conds.append(and_(*parts))
        return or_(*conds) if conds else ~true()

    @staticmethod
    def _matches(f, lanes: list[dict], r) -> bool:
        return (
            f.status == "active"
            and "," + r.mode + "," in f.modes
            and "," + r.incoterm + "," in f.incoterms
            and any(
                ln["origin_country"] in ("*", r.origin_country)
                and ln["destination_country"] in ("*", r.destination_country)
                for ln in lanes
            )
        )

    async def create_request(self, user: str, body: RequestCreate) -> dict:
        try:
            ready = date.fromisoformat(body.ready_date)
        except ValueError:
            raise Invalid("ready_date must be an ISO date (YYYY-MM-DD)", code="invalid_ready_date") from None
        t = self.clock()
        today = t.date()
        if ready < today or ready > today + timedelta(days=MAX_READY_DAYS):
            raise Invalid(
                f"ready_date must be between today and {MAX_READY_DAYS} days ahead", code="invalid_ready_date"
            )
        await self._rate(user, "requests")
        self._screen(
            {
                "cargo_description": body.cargo_description,
                "origin_place": body.origin_place,
                "destination_place": body.destination_place,
            }
        )
        rid = _new_id("shp")
        async with self.engine.begin() as c:
            await self._expire(c)
            n = await c.scalar(
                select(func.count()).select_from(R).where(R.c.buyer_id == user, R.c.status == "open")
            )
            if (n or 0) >= self.s.max_open_requests_per_buyer:
                raise Conflict("Open request limit reached; close an old request first", code="request_limit_reached")
            await c.execute(
                insert(R).values(
                    id=rid, buyer_id=user, origin_country=body.origin_country, origin_place=body.origin_place,
                    destination_country=body.destination_country, destination_place=body.destination_place,
                    cargo_description=body.cargo_description, hs_code=body.hs_code,
                    weight_kg=_wt(body.weight_kg), volume_cbm=_wt(body.volume_cbm), mode=body.mode,
                    container_type=body.container_type,
                    container_count=(body.container_count or 1) if body.container_type else None,
                    incoterm=body.incoterm, ready_date=ready, currency=body.currency,
                    landed_cost_ref=body.landed_cost_ref, status="open", visibility="visible",
                    quote_count=0, report_count=0, expires_at=t + timedelta(days=body.quote_deadline_days),
                    created_at=t,
                )  # fmt: skip
            )
            r = (await c.execute(select(R).where(R.c.id == rid))).one()
        return self._request(r, "owner")

    async def list_requests(self, user: str, status: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        async with self.engine.begin() as c:
            await self._expire(c)
            q = select(R).where(R.c.buyer_id == user, R.c.visibility == "visible")
            if status:
                q = q.where(R.c.status == status)
            q = self._after_time(q, cursor, R)
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, lambda r: self._request(r, "owner"))

    async def inbox(self, user: str, cursor: str | None, limit: int | None) -> dict:
        """Open requests matching the forwarder's lanes, modes and incoterms (newest first)."""
        limit = self._limit(limit)
        async with self.engine.begin() as c:
            await self._expire(c)
            f = await self._require_forwarder(c, user)
            lanes = (await self._lanes(c, [f.id]))[f.id]
            q = select(R).where(
                R.c.status == "open", R.c.visibility == "visible", R.c.buyer_id != user,
                R.c.mode.in_(csv_list(f.modes)), R.c.incoterm.in_(csv_list(f.incoterms)),
                self._lane_match(lanes),
            )  # fmt: skip
            q = self._after_time(q, cursor, R)
            rows = (await c.execute(q.limit(limit + 1))).all()
            quoted = set()
            if rows:
                quoted = {
                    x[0]
                    for x in await c.execute(
                        select(quotes.c.request_id).where(
                            quotes.c.forwarder_id == f.id, quotes.c.request_id.in_([r.id for r in rows])
                        )
                    )
                }
        return self._page_of(rows, limit, lambda r: {**self._request(r, "forwarder"), "has_quoted": r.id in quoted})

    async def _load_request(self, c, rid: str):
        r = (await c.execute(select(R).where(R.c.id == rid))).first()
        if r is None or r.visibility != "visible":
            raise NotFound("Request not found")
        return r

    async def _view_for(self, c, user: str, r) -> str:
        """The caller's view of a request, or NotFound when it must not see it."""
        if r.buyer_id == user:
            return "owner"
        f = await self._forwarder_of(c, user)
        if f is not None:
            if r.awarded_forwarder_id == f.id:
                return "winner"
            has_quote = await c.scalar(
                select(func.count()).select_from(quotes).where(quotes.c.request_id == r.id, quotes.c.forwarder_id == f.id)
            )
            if has_quote:
                return "forwarder"
            lanes = (await self._lanes(c, [f.id]))[f.id]
            if r.status == "open" and self._matches(f, lanes, r):
                return "forwarder"
        raise NotFound("Request not found")

    async def get_request(self, user: str, rid: str) -> dict:
        async with self.engine.begin() as c:
            await self._expire(c)
            r = await self._load_request(c, rid)
            view = await self._view_for(c, user, r)
        return self._request(r, view)

    async def close_request(self, user: str, rid: str) -> dict:
        """Buyer closes: open -> closed (cancelled), awarded -> closed (completed). Idempotent."""
        t = self.clock()
        async with self.engine.begin() as c:
            await self._expire(c)
            r = await self._load_request(c, rid)
            if r.buyer_id != user:
                raise NotFound("Request not found")
            if r.status == "closed":
                return self._request(r, "owner")
            if r.status == "expired":
                raise Conflict("The request already expired", code="request_expired")
            res = await c.execute(
                update(R).where(R.c.id == rid, R.c.status == r.status).values(status="closed", closed_at=t)
            )
            if not res.rowcount:
                raise Conflict("The request changed; retry", code="state_changed")
            if r.status == "awarded":
                await c.execute(
                    update(forwarders)
                    .where(forwarders.c.id == r.awarded_forwarder_id)
                    .values(completed_count=forwarders.c.completed_count + 1)
                )
            else:  # cancelled while open: pending quotes are rejected
                await c.execute(
                    update(quotes).where(quotes.c.request_id == rid, quotes.c.status == "submitted").values(status="rejected")
                )
                await self._recount(c, rid)
            r = (await c.execute(select(R).where(R.c.id == rid))).one()
        return self._request(r, "owner")

    @staticmethod
    async def _recount(c, rid: str) -> None:
        n = await c.scalar(
            select(func.count()).select_from(quotes).where(
                quotes.c.request_id == rid, quotes.c.status.in_(("submitted", "accepted"))
            )
        )
        await c.execute(update(R).where(R.c.id == rid).values(quote_count=n or 0))

    # ------------------------------------------------------------------ quotes
    def _check_quote_money(self, req, body: QuoteCreate) -> None:
        if body.currency != req.currency:
            raise Invalid(
                f"Quote currency must be {req.currency} (the request currency)", code="currency_mismatch",
                details={"expected": req.currency},
            )  # fmt: skip
        if body.breakdown:
            total = sum((x.amount for x in body.breakdown), Decimal(0))
            if total.quantize(Q2) != body.amount.quantize(Q2):
                raise Invalid("breakdown lines must add up to amount", code="breakdown_mismatch")

    def _screen_quote(self, body: QuoteCreate) -> None:
        self._screen(
            {
                "inclusions": " ; ".join(body.inclusions),
                "exclusions": " ; ".join(body.exclusions),
                "breakdown": " ; ".join(x.label for x in body.breakdown),
                "terms": body.terms,
            }
        )

    async def _open_matching_request(self, c, f, rid: str):
        """The request a forwarder may quote on: visible, open, lane/mode/incoterm match."""
        r = await self._load_request(c, rid)
        lanes = (await self._lanes(c, [f.id]))[f.id]
        matches = self._matches(f, lanes, r)
        has_quote = await c.scalar(
            select(func.count()).select_from(quotes).where(quotes.c.request_id == rid, quotes.c.forwarder_id == f.id)
        )
        if not has_quote and not matches:
            raise NotFound("Request not found")
        if r.status != "open":
            raise Conflict("The request is no longer open", code="request_not_open", details={"status": r.status})
        if not matches:
            raise Forbidden("The request no longer matches your lanes, modes or incoterms", code="lane_mismatch")
        return r

    async def submit_quote(self, user: str, rid: str, body: QuoteCreate) -> dict:
        async with self.engine.connect() as c:
            f = await self._require_forwarder(c, user)
        await self._rate(user, "quotes")
        self._screen_quote(body)
        t = self.clock()
        qid = _new_id("qte")
        try:
            async with self.engine.begin() as c:
                await self._expire(c)
                r = await self._open_matching_request(c, f, rid)
                if r.buyer_id == user:
                    raise Forbidden("You cannot quote on your own request", code="own_request")
                self._check_quote_money(r, body)
                if await c.scalar(
                    select(func.count()).select_from(quotes).where(quotes.c.request_id == rid, quotes.c.forwarder_id == f.id)
                ):
                    raise Conflict("You already quoted on this request; revise it instead", code="quote_exists")
                if r.quote_count >= self.s.max_quotes_per_request:
                    raise Conflict("This request reached its quote limit", code="quote_limit_reached")
                await c.execute(
                    insert(quotes).values(
                        id=qid, request_id=rid, forwarder_id=f.id, amount=_money(body.amount), currency=body.currency,
                        transit_days=body.transit_days, valid_until=t + timedelta(days=body.valid_days),
                        inclusions=body.inclusions, exclusions=body.exclusions,
                        breakdown=[{"label": x.label, "amount": _money(x.amount)} for x in body.breakdown],
                        terms=body.terms, status="submitted", visibility="visible", report_count=0,
                        revision=1, created_at=t, updated_at=t,
                    )  # fmt: skip
                )
                await self._recount(c, rid)
                q = (await c.execute(select(quotes).where(quotes.c.id == qid))).one()
        except IntegrityError:
            raise Conflict("You already quoted on this request; revise it instead", code="quote_exists") from None
        return self._quote(q, f)

    async def _own_quote(self, c, user: str, qid: str):
        f = await self._require_forwarder(c, user, active=False)
        q = (await c.execute(select(quotes).where(quotes.c.id == qid, quotes.c.forwarder_id == f.id))).first()
        if q is None or q.visibility != "visible":
            raise NotFound("Quote not found")
        return f, q

    async def revise_quote(self, user: str, qid: str, body: QuoteCreate) -> dict:
        self._screen_quote(body)
        t = self.clock()
        async with self.engine.begin() as c:
            await self._expire(c)
            f, q = await self._own_quote(c, user, qid)
            if f.status != "active":
                raise Forbidden("This forwarder account is suspended", code="forwarder_suspended")
            if q.status not in ("submitted", "withdrawn"):
                raise Conflict("This quote can no longer be changed", code="quote_final", details={"status": q.status})
            r = await self._open_matching_request(c, f, q.request_id)
            self._check_quote_money(r, body)
            if q.status == "withdrawn" and r.quote_count >= self.s.max_quotes_per_request:
                raise Conflict("This request reached its quote limit", code="quote_limit_reached")
            await c.execute(
                update(quotes).where(quotes.c.id == qid).values(
                    amount=_money(body.amount), currency=body.currency, transit_days=body.transit_days,
                    valid_until=t + timedelta(days=body.valid_days), inclusions=body.inclusions,
                    exclusions=body.exclusions,
                    breakdown=[{"label": x.label, "amount": _money(x.amount)} for x in body.breakdown],
                    terms=body.terms, status="submitted", revision=q.revision + 1, updated_at=t,
                )  # fmt: skip
            )
            await self._recount(c, q.request_id)
            q = (await c.execute(select(quotes).where(quotes.c.id == qid))).one()
        return self._quote(q, f)

    async def withdraw_quote(self, user: str, qid: str) -> dict:
        t = self.clock()
        async with self.engine.begin() as c:
            await self._expire(c)
            f, q = await self._own_quote(c, user, qid)
            if q.status == "withdrawn":
                return self._quote(q, f)
            if q.status != "submitted":
                raise Conflict("This quote can no longer be withdrawn", code="quote_final", details={"status": q.status})
            await c.execute(update(quotes).where(quotes.c.id == qid).values(status="withdrawn", updated_at=t))
            await self._recount(c, q.request_id)
            q = (await c.execute(select(quotes).where(quotes.c.id == qid))).one()
        return self._quote(q, f)

    async def my_quotes(self, user: str, status: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        async with self.engine.connect() as c:
            f = await self._require_forwarder(c, user, active=False)
            q = select(quotes).where(quotes.c.forwarder_id == f.id, quotes.c.visibility == "visible")
            if status:
                q = q.where(quotes.c.status == status)
            q = self._after_time(q, cursor, quotes)
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, lambda r: self._quote(r))

    async def get_quote(self, user: str, qid: str) -> dict:
        async with self.engine.connect() as c:
            q = (await c.execute(select(quotes).where(quotes.c.id == qid))).first()
            if q is None or q.visibility != "visible":
                raise NotFound("Quote not found")
            req = (await c.execute(select(R).where(R.c.id == q.request_id))).one()
            f = (await c.execute(select(forwarders).where(forwarders.c.id == q.forwarder_id))).one()
            if f.user_id != user and not (req.buyer_id == user and req.visibility == "visible"):
                raise NotFound("Quote not found")
        return self._quote(q, f)

    async def list_quotes(self, user: str, rid: str, status: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        async with self.engine.begin() as c:
            await self._expire(c)
            r = await self._load_request(c, rid)
            if r.buyer_id != user:
                raise NotFound("Request not found")
            q = select(quotes).where(quotes.c.request_id == rid, quotes.c.visibility == "visible")
            q = q.where(quotes.c.status == status) if status else q.where(quotes.c.status != "withdrawn")
            q = self._after_time(q, cursor, quotes)
            rows = (await c.execute(q.limit(limit + 1))).all()
            fw = await self._fwd_map(c, [x.forwarder_id for x in rows[:limit]])
        return self._page_of(rows, limit, lambda x: self._quote(x, fw[x.forwarder_id]))

    @staticmethod
    async def _fwd_map(c, ids: list[str]) -> dict:
        if not ids:
            return {}
        rows = await c.execute(select(forwarders).where(forwarders.c.id.in_(set(ids))))
        return {r.id: r for r in rows}

    async def comparison(self, user: str, rid: str, sort: str = "score") -> dict:
        t = self.clock()
        async with self.engine.begin() as c:
            await self._expire(c)
            r = await self._load_request(c, rid)
            if r.buyer_id != user:
                raise NotFound("Request not found")
            statuses = ("submitted",) if r.status == "open" else ("submitted", "accepted")
            rows = (
                await c.execute(
                    select(quotes).where(
                        quotes.c.request_id == rid, quotes.c.visibility == "visible", quotes.c.status.in_(statuses)
                    ).order_by(quotes.c.created_at, quotes.c.id)
                )
            ).all()
            fw = await self._fwd_map(c, [x.forwarder_id for x in rows])
        cands: list[Candidate] = []
        by_id = {}
        excluded = []
        for x in rows:
            f = fw[x.forwarder_id]
            if f.status != "active":
                excluded.append({"quote_id": x.id, "reason": "forwarder_suspended"})
            elif x.currency != r.currency:
                excluded.append({"quote_id": x.id, "reason": "currency_mismatch"})
            elif r.status == "open" and x.valid_until <= t:
                excluded.append({"quote_id": x.id, "reason": "quote_expired"})
            else:
                by_id[x.id] = x
                cands.append(
                    Candidate(x.id, Decimal(x.amount), x.transit_days, f.rating_sum, f.rating_count, _iso(x.created_at) or "")
                )
        w = normalise_weights(self.s.weight_price, self.s.weight_transit, self.s.weight_rating)
        ranked = rank(cands, w, sort)
        items = []
        for row in ranked:
            x = by_id[row["quote_id"]]
            items.append(
                {
                    "rank": row["rank"],
                    "score": _f(row["score"]),
                    "breakdown": {
                        k: {"value": _f(v["value"]), "weight": _f(v["weight"])} for k, v in row["breakdown"].items()
                    },
                    "adjusted_rating": _f(row["adjusted_rating"]),
                    "badges": row["badges"],
                    "explanation": row["explanation"],
                    "quote": self._quote(x, fw[x.forwarder_id]),
                }
            )
        return {
            "request_id": rid,
            "request_status": r.status,
            "currency": r.currency,
            "sort": sort,
            "weights": {"price": _f(w[0]), "transit": _f(w[1]), "rating": _f(w[2])},
            "formula": FORMULA,
            "items": items,
            "excluded": excluded,
        }

    async def accept_quote(self, user: str, qid: str, expected_revision: int | None = None) -> dict:
        """Award the request to a quote. Idempotent for the already-accepted quote."""
        t = self.clock()
        async with self.engine.begin() as c:
            await self._expire(c)
            q = (await c.execute(select(quotes).where(quotes.c.id == qid))).first()
            if q is None or q.visibility != "visible":
                raise NotFound("Quote not found")
            r = await self._load_request(c, q.request_id)
            if r.buyer_id != user:
                raise NotFound("Quote not found")
            f = (await c.execute(select(forwarders).where(forwarders.c.id == q.forwarder_id))).one()
            if r.awarded_quote_id == qid:  # retry of a successful accept
                return {"request": self._request(r, "owner"), "quote": self._quote(q, f)}
            if r.status in ("awarded", "closed") and r.awarded_quote_id:
                raise Conflict("The request is already awarded to another quote", code="already_awarded")
            if r.status != "open":
                code = "request_expired" if r.status == "expired" else "request_not_open"
                raise Conflict("The request is not open", code=code, details={"status": r.status})
            if q.status != "submitted":
                raise Conflict("This quote is not available", code="quote_not_available", details={"status": q.status})
            if q.valid_until <= t:
                raise Conflict("This quote has expired", code="quote_expired")
            if expected_revision is not None and q.revision != expected_revision:
                raise Conflict(
                    "The quote was revised after you viewed it; review it again", code="quote_changed",
                    details={"revision": q.revision},
                )
            if f.status != "active":
                raise Conflict("The forwarder is suspended", code="forwarder_suspended")
            won = await c.execute(
                update(R).where(R.c.id == r.id, R.c.status == "open").values(
                    status="awarded", awarded_quote_id=qid, awarded_forwarder_id=q.forwarder_id, awarded_at=t
                )
            )
            if not won.rowcount:  # lost a race with a concurrent accept/close/expiry
                raise Conflict("The request is no longer open", code="state_changed")
            # CAS on the exact revision read above: a concurrent revise/withdraw must not slip in under the accept
            took = await c.execute(
                update(quotes).where(quotes.c.id == qid, quotes.c.status == "submitted", quotes.c.revision == q.revision)
                .values(status="accepted", updated_at=t)
            )
            if not took.rowcount:
                raise Conflict("The quote changed while accepting; retry", code="quote_changed")
            await c.execute(
                update(quotes).where(quotes.c.request_id == r.id, quotes.c.id != qid, quotes.c.status == "submitted")
                .values(status="rejected", updated_at=t)
            )  # fmt: skip
            await self._recount(c, r.id)
            r = (await c.execute(select(R).where(R.c.id == r.id))).one()
            q = (await c.execute(select(quotes).where(quotes.c.id == qid))).one()
        return {"request": self._request(r, "owner"), "quote": self._quote(q, f)}

    # ------------------------------------------------------------------ ratings
    async def rate(self, user: str, rid: str, body: RatingIn) -> dict:
        await self._rate(user, "ratings")
        self._screen({"comment": body.comment})
        t = self.clock()
        try:
            async with self.engine.begin() as c:
                r = await self._load_request(c, rid)
                if r.buyer_id != user:
                    raise NotFound("Request not found")
                if r.status != "closed" or not r.awarded_forwarder_id:
                    raise Conflict("Only a completed (awarded and closed) request can be rated", code="not_completed")
                if await c.scalar(select(func.count()).select_from(ratings).where(ratings.c.request_id == rid)):
                    raise Conflict("This shipment is already rated", code="already_rated")
                # anti-farming: no proof of shipment exists yet, so make ratings slow and bounded per buyer/forwarder pair
                if self.s.rating_min_delay_seconds and r.closed_at is not None:
                    wait = _aware(r.closed_at) + timedelta(seconds=self.s.rating_min_delay_seconds) - t
                    if wait.total_seconds() > 0:
                        raise Conflict("Ratings open some time after the request is closed", code="rating_too_early")
                if self.s.rating_max_per_pair:
                    since = t - timedelta(days=self.s.rating_pair_window_days)
                    n = await c.scalar(
                        select(func.count()).select_from(ratings).where(
                            ratings.c.buyer_id == user, ratings.c.forwarder_id == r.awarded_forwarder_id,
                            ratings.c.created_at > since,
                        )
                    )
                    if n >= self.s.rating_max_per_pair:
                        raise Conflict("You have rated this forwarder too often", code="rating_pair_limit")
                row = {"id": _new_id("rat"), "request_id": rid, "forwarder_id": r.awarded_forwarder_id,
                       "buyer_id": user, "stars": body.stars, "comment": body.comment, "created_at": t}  # fmt: skip
                await c.execute(insert(ratings).values(**row))
                await c.execute(
                    update(forwarders).where(forwarders.c.id == r.awarded_forwarder_id).values(
                        rating_sum=forwarders.c.rating_sum + body.stars, rating_count=forwarders.c.rating_count + 1
                    )
                )
        except IntegrityError:
            raise Conflict("This shipment is already rated", code="already_rated") from None
        return self._rating_row(SimpleNamespace(**row))

    # ------------------------------------------------------------------ reports
    async def report(self, user: str, kind: str, target_id: str, reason: str, details: str | None) -> dict:
        async with self.engine.begin() as c:
            await self._expire(c)
            if kind == "request":
                r = await self._load_request(c, target_id)
                if r.buyer_id == user:
                    raise Invalid("You cannot report your own content", code="cannot_report_own")
                await self._view_for(c, user, r)  # only parties who can see it may report it
            elif kind == "quote":
                q = (await c.execute(select(quotes).where(quotes.c.id == target_id))).first()
                if q is None or q.visibility != "visible":
                    raise NotFound("Quote not found")
                r = await self._load_request(c, q.request_id)
                if r.buyer_id != user:
                    raise NotFound("Quote not found")
            else:
                f = (await c.execute(select(forwarders).where(forwarders.c.id == target_id))).first()
                if f is None or f.status != "active":
                    raise NotFound("Forwarder not found")
                if f.user_id == user:
                    raise Invalid("You cannot report your own content", code="cannot_report_own")
                dealt = await c.scalar(
                    select(func.count()).select_from(quotes.join(R, R.c.id == quotes.c.request_id)).where(
                        quotes.c.forwarder_id == target_id, R.c.buyer_id == user
                    )
                )
                if not dealt:
                    raise NotFound("Forwarder not found")
        await self._rate(user, "reports")
        clean = redact(details.strip())[:300] if details and details.strip() else None
        try:
            async with self.engine.begin() as c:
                if await c.scalar(
                    select(func.count()).select_from(reports).where(
                        reports.c.target_type == kind, reports.c.target_id == target_id, reports.c.reporter_id == user
                    )
                ):
                    return {"status": "received"}
                await c.execute(
                    insert(reports).values(
                        id=_new_id("rep"), target_type=kind, target_id=target_id, reporter_id=user,
                        reason=reason, details=clean, created_at=self.clock(),
                    )  # fmt: skip
                )
                n = await c.scalar(
                    select(func.count()).select_from(reports).where(
                        reports.c.target_type == kind, reports.c.target_id == target_id
                    )
                )
                tbl = {"request": R, "quote": quotes}.get(kind)
                if tbl is not None:  # forwarders are never auto-actioned; admins review their reports
                    vals: dict = {"report_count": n}
                    eligible = await self._eligible_reporters(c, kind, target_id)
                    in_flight = kind == "request" and (await self._load_request(c, target_id)).status == "awarded"
                    if eligible >= self.s.report_hide_threshold and not in_flight:  # a deal in progress is left to admins
                        vals |= {"visibility": "hidden", "hidden_reason": "auto: report threshold reached"}
                    await c.execute(update(tbl).where(tbl.c.id == target_id, tbl.c.visibility == "visible").values(**vals))
        except IntegrityError:
            pass  # concurrent identical report
        return {"status": "received"}

    async def _eligible_reporters(self, c, kind: str, target_id: str) -> int:
        """Distinct reporters old enough to count toward auto-hide (throwaway accounts cannot hide a competitor)."""
        ids = (await c.execute(select(reports.c.reporter_id).where(reports.c.target_type == kind, reports.c.target_id == target_id))).scalars().all()
        age = self.s.report_min_account_age_seconds
        if not age:
            return len(set(ids))
        cutoff = self.clock() - timedelta(seconds=age)
        ok = 0
        for uid in set(ids):
            born = await c.scalar(select(func.min(forwarders.c.created_at)).where(forwarders.c.user_id == uid))
            first_req = await c.scalar(select(func.min(R.c.created_at)).where(R.c.buyer_id == uid))
            stamps = [_aware(x) for x in (born, first_req) if x is not None]
            if stamps and min(stamps) <= cutoff:
                ok += 1
        return ok

    # ------------------------------------------------------------------ admin
    async def admin_applications(self, status: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(applications)
        if status != "all":
            q = q.where(applications.c.status == status)
        q = self._after_time(q, cursor, applications)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, lambda r: self._application(r, admin=True))

    async def admin_approve(self, app_id: str, note: str | None) -> dict:
        t = self.clock()
        async with self.engine.begin() as c:
            a = (await c.execute(select(applications).where(applications.c.id == app_id))).first()
            if a is None:
                raise NotFound("Application not found")
            if a.status == "approved":  # idempotent
                return self._application(a, admin=True)
            if a.status != "pending":
                raise Conflict("The application was already rejected", code="already_reviewed")
            if await self._forwarder_of(c, a.user_id):
                raise Conflict("This user is already a forwarder", code="already_forwarder")
            fid = _new_id("fwd")
            await c.execute(
                insert(forwarders).values(
                    id=fid, user_id=a.user_id, company_name=a.company_name, country_code=a.country_code,
                    description=a.description, modes=a.modes, incoterms=a.incoterms,
                    certifications=a.certifications, status="active", rating_sum=0, rating_count=0,
                    completed_count=0, verified_at=t, created_at=t,
                )  # fmt: skip
            )
            lanes = sorted({(o, d) for o, d in a.lanes})
            await c.execute(
                insert(forwarder_lanes),
                [{"forwarder_id": fid, "origin_country": o, "destination_country": d} for o, d in lanes],
            )
            await c.execute(
                update(applications).where(applications.c.id == app_id).values(
                    status="approved", forwarder_id=fid, review_note=note, reviewed_at=t
                )
            )
            a = (await c.execute(select(applications).where(applications.c.id == app_id))).one()
        return self._application(a, admin=True)

    async def admin_reject(self, app_id: str, reason: str) -> dict:
        t = self.clock()
        async with self.engine.begin() as c:
            a = (await c.execute(select(applications).where(applications.c.id == app_id))).first()
            if a is None:
                raise NotFound("Application not found")
            if a.status == "approved":
                raise Conflict("The application was already approved", code="already_reviewed")
            if a.status == "pending":
                await c.execute(
                    update(applications).where(applications.c.id == app_id).values(
                        status="rejected", review_note=reason, reviewed_at=t
                    )
                )
                a = (await c.execute(select(applications).where(applications.c.id == app_id))).one()
        return self._application(a, admin=True)

    async def admin_forwarders(self, status: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(forwarders)
        if status != "all":
            q = q.where(forwarders.c.status == status)
        q = self._after_time(q, cursor, forwarders)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
            lanes = await self._lanes(c, [r.id for r in rows[:limit]])
        return self._page_of(rows, limit, lambda r: self._forwarder(r, lanes[r.id], admin=True))

    async def admin_set_forwarder(self, fid: str, suspend: bool, reason: str | None) -> dict:
        async with self.engine.begin() as c:
            if not (await c.scalar(select(func.count()).select_from(forwarders).where(forwarders.c.id == fid))):
                raise NotFound("Forwarder not found")
            vals = (
                {"status": "suspended", "status_reason": f"admin: {reason}"[:300]}
                if suspend
                else {"status": "active", "status_reason": None}
            )
            await c.execute(update(forwarders).where(forwarders.c.id == fid).values(**vals))
            f = (await c.execute(select(forwarders).where(forwarders.c.id == fid))).one()
            lanes = (await self._lanes(c, [fid]))[fid]
        return self._forwarder(f, lanes, admin=True)

    async def admin_requests(self, status: str, visibility: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        async with self.engine.begin() as c:
            await self._expire(c)
            q = select(R)
            if status != "all":
                q = q.where(R.c.status == status)
            if visibility != "all":
                q = q.where(R.c.visibility == visibility)
            q = self._after_time(q, cursor, R)
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, lambda r: self._request(r, "admin"))

    async def admin_set_request(self, rid: str, hide: bool, reason: str | None) -> dict:
        return await self._admin_visibility(R, "request", rid, hide, reason, lambda r: self._request(r, "admin"))

    async def admin_quotes(self, request_id: str | None, visibility: str, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(quotes)
        if request_id:
            q = q.where(quotes.c.request_id == request_id)
        if visibility != "all":
            q = q.where(quotes.c.visibility == visibility)
        q = self._after_time(q, cursor, quotes)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(rows, limit, lambda r: self._quote(r, admin=True))

    async def admin_set_quote(self, qid: str, hide: bool, reason: str | None) -> dict:
        return await self._admin_visibility(quotes, "quote", qid, hide, reason, lambda r: self._quote(r, admin=True))

    async def _admin_visibility(self, tbl, kind: str, ident: str, hide: bool, reason: str | None, mapper) -> dict:
        async with self.engine.begin() as c:
            if not (await c.scalar(select(func.count()).select_from(tbl).where(tbl.c.id == ident))):
                raise NotFound(f"{kind.capitalize()} not found")
            if hide:
                vals = {"visibility": "hidden", "hidden_reason": f"admin: {reason}"[:300]}
            else:  # restore: earlier reports no longer count toward the threshold
                vals = {"visibility": "visible", "hidden_reason": None, "report_count": 0}
                await c.execute(delete(reports).where(reports.c.target_type == kind, reports.c.target_id == ident))
            await c.execute(update(tbl).where(tbl.c.id == ident).values(**vals))
            r = (await c.execute(select(tbl).where(tbl.c.id == ident))).one()
        return mapper(r)

    async def admin_reports(self, target_type: str | None, target_id: str | None, cursor: str | None, limit: int | None) -> dict:
        limit = self._limit(limit)
        q = select(reports)
        if target_type:
            q = q.where(reports.c.target_type == target_type)
        if target_id:
            q = q.where(reports.c.target_id == target_id)
        q = self._after_time(q, cursor, reports)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.limit(limit + 1))).all()
        return self._page_of(
            rows, limit,
            lambda r: {"id": r.id, "target_type": r.target_type, "target_id": r.target_id,
                       "reporter_id": r.reporter_id, "reason": r.reason, "details": r.details,
                       "created_at": _iso(r.created_at)},
        )  # fmt: skip

    async def admin_sweep(self) -> dict:
        async with self.engine.begin() as c:
            n = await self._expire(c)
        return {"expired": n}
