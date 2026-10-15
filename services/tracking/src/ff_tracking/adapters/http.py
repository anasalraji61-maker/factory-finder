"""Licensed-API tracking providers (OFF by default; CLAUDE.md rules 4, 5, 6).

``HttpContainerProvider`` (container / bill of lading), ``HttpAwbProvider`` (air waybill) and
``HttpVesselPositionProvider`` (AIS position + ETA only) are skeletons for aggregator-style
APIs. **Every wire shape below is UNVERIFIED**: no live provider was available, the parsers are
driven by recorded JSON fixtures in ``tests/fixtures`` and must be re-checked against the real
provider's documentation before it is switched on.

Compliance built in: official/licensed API only (never carrier/AIS-site scraping), >= 3 s between
requests per host (clamped floor), response cache, honest User-Agent, key from env only (never
printed), global + per-provider kill switch, cooldown after failures. 401/403/429/5xx/timeouts
all raise ``ProviderUnavailable`` with a short ``reason``; callers fall back to the mock with a
``warning``. Nothing retries or bypasses.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ff_tracking.adapters.base import ProviderUnavailable, VesselEta
from ff_tracking.domain.carriers import carrier_for_awb_prefix, carrier_for_bl_prefix, find_carrier
from ff_tracking.domain.dcsa import dcsa_raw_events, is_dcsa
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.models import CarrierRef, GeoPoint, TrackingSnapshot, VesselRef
from ff_tracking.domain.normalize import location_of, normalize_events, parse_ts, resolve_location
from ff_tracking.domain.validators import parse_vessel

GLOBAL_KILL_SWITCH_ENV = "FF_TRACKING_KILL_SWITCH"
MIN_INTERVAL_FLOOR_S = 3.0
MAX_CACHE_ENTRIES = 1000
MAX_BODY_BYTES = 1_048_576  # provider responses larger than this are rejected before JSON parsing
_FORMAT = {  # defence in depth: never put an unvalidated string into a provider URL
    "container": re.compile(r"[A-Z]{3}[UJZ][0-9]{7}"), "bl": re.compile(r"[A-Z]{4}[A-Z0-9]{4,16}"),
    "awb": re.compile(r"[0-9]{3}-[0-9]{8}"), "imo": re.compile(r"[0-9]{7}"),
}


def _check(kind: str, value: str, pid: str) -> None:
    if not _FORMAT[kind].fullmatch(value or ""):
        raise ProviderUnavailable(f"{pid}: malformed reference", reason="unsupported")
USER_AGENT = "FactoryFinderBot/0.1 (+https://github.com/factory-finder; tracking)"
_TRUTHY = {"1", "true", "yes", "on"}


class _HttpBase:
    """Kill switch, key, per-host rate limit, cache and cooldown shared by every skeleton."""

    id = "http"
    kill_switch_env = "FF_TRACKING_HTTP_DISABLED"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        user_agent: str = USER_AGENT,
        min_interval_s: float = MIN_INTERVAL_FLOOR_S,
        cache_ttl_s: float = 3600.0,
        cooldown_s: float = 60.0,
        timeout_s: float = 8.0,
        kill_switch_env: str | None = None,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url, self._key, self.user_agent = base_url.rstrip("/"), api_key, user_agent
        self.min_interval_s = max(min_interval_s, MIN_INTERVAL_FLOOR_S)
        self.cache_ttl_s, self.cooldown_s, self.timeout_s = cache_ttl_s, cooldown_s, timeout_s
        self._kill_env = kill_switch_env or self.kill_switch_env
        self._env = env if env is not None else os.environ
        self._client, self._clock, self._sleep = client, clock, sleep
        self._cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
        self._next_at: dict[str, float] = {}
        self._cooldown_until = 0.0
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:  # never expose the key
        return f"<{type(self).__name__} {self.base_url} configured={self.configured()}>"

    def configured(self) -> bool:
        return bool(self.base_url and self._key)

    def killed(self) -> bool:
        return any(n and self._env.get(n, "").strip().lower() in _TRUTHY
                   for n in (GLOBAL_KILL_SWITCH_ENV, self._kill_env))

    def _guard(self) -> None:
        if self.killed():
            raise ProviderUnavailable(f"{self.id}: kill switch is on", reason="kill_switch")
        if not self.configured():
            raise ProviderUnavailable(f"{self.id}: not configured", reason="not_configured")

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self._guard()
        params = params or {}
        url = f"{self.base_url}{path}"
        key = (url, tuple(sorted(params.items())))
        async with self._lock:
            now = self._clock()
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1]
            if now < self._cooldown_until:
                raise ProviderUnavailable(f"{self.id}: cooling down after errors", reason="cooldown")
            host = urlsplit(url).netloc
            ready = self._next_at.get(host, 0.0)
            if ready > now:
                await self._sleep(ready - now)
                now = ready
            self._next_at[host] = now + self.min_interval_s
            try:
                data = await self._request(url, params)
            except ProviderUnavailable:
                self._cooldown_until = self._clock() + self.cooldown_s
                raise
            if len(self._cache) >= MAX_CACHE_ENTRIES:  # bounded: drop expired, then the oldest
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
                while len(self._cache) >= MAX_CACHE_ENTRIES:
                    self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (self._clock() + self.cache_ttl_s, data)
            return data

    async def _request(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            async with client.stream("GET", url, params=params, headers={
                    "User-Agent": self.user_agent, "Accept": "application/json",
                    "Authorization": f"Bearer {self._key}"}) as r:
                if r.status_code == 429:
                    raise ProviderUnavailable(f"{self.id}: HTTP 429; not retrying", reason="rate_limited")
                if r.status_code in (401, 403):
                    raise ProviderUnavailable(f"{self.id}: HTTP {r.status_code}; not retrying", reason="blocked")
                if r.status_code >= 400:
                    raise ProviderUnavailable(f"{self.id}: HTTP {r.status_code}", reason="upstream_error")
                declared = r.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                    raise ProviderUnavailable(f"{self.id}: response too large", reason="bad_payload")
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY_BYTES:
                        raise ProviderUnavailable(f"{self.id}: response too large", reason="bad_payload")
            data = json.loads(bytes(body))
            if not isinstance(data, dict):
                raise ValueError("payload is not an object")
            return data
        except ProviderUnavailable:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"{self.id}: timeout", reason="timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.id}: {type(exc).__name__}", reason="upstream_error") from exc
        except ValueError as exc:
            raise ProviderUnavailable(f"{self.id}: bad JSON", reason="bad_payload") from exc
        finally:
            if self._client is None:
                await client.aclose()


def _vessel(v: Any) -> VesselRef | None:
    return parse_vessel(v)


class HttpContainerProvider(_HttpBase):
    """Aggregator-style container / B/L tracking: GET /v1/containers/{no}?carrier=SCAC (UNVERIFIED)."""

    id = "http_container"
    kill_switch_env = "FF_TRACKING_CONTAINER_DISABLED"

    @staticmethod
    def detect_scac(reference: str, reference_type: ReferenceType, carrier: CarrierRef | None) -> str | None:
        if carrier and carrier.scac:
            return carrier.scac
        if reference_type is ReferenceType.CONTAINER:
            from ff_tracking.domain.carriers import carrier_for_container_owner
            c = carrier_for_container_owner(reference[:4])
        else:
            c = carrier_for_bl_prefix(reference[:4])
        return c.scac if c else None

    async def track(self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
                    *, anchor: datetime, now: datetime) -> TrackingSnapshot:
        if reference_type not in (ReferenceType.CONTAINER, ReferenceType.BL):
            raise ProviderUnavailable(f"{self.id}: unsupported reference type", reason="unsupported")
        _check("container" if reference_type is ReferenceType.CONTAINER else "bl", reference, self.id)
        scac = self.detect_scac(reference, reference_type, carrier)
        if reference_type is ReferenceType.BL and not scac:
            raise ProviderUnavailable(f"{self.id}: B/L needs a carrier", reason="unsupported")
        path = ("/v1/containers/" if reference_type is ReferenceType.CONTAINER else "/v1/bills-of-lading/")
        payload = await self._get_json(path + quote(reference, safe=""), {"carrier": scac} if scac else {})
        return self.parse(payload, now=now, carrier=carrier, scac=scac)

    def parse(self, payload: dict[str, Any], *, now: datetime, carrier: CarrierRef | None = None,
              scac: str | None = None) -> TrackingSnapshot:
        """UNVERIFIED shape: data.{events[{id,type,description,occurred_at,actual,location{unlocode,
        name,country,lat,lon},vessel}],eta,origin.unlocode,destination.unlocode,vessel,carrier.scac}."""
        try:
            if is_dcsa(payload):  # DCSA Track & Trace events: no envelope, destination/ETA come from the events
                d = {"events": [], "destination": {"unlocode": payload.get("destination")}, "origin": {"unlocode": payload.get("origin")}}
                raw = dcsa_raw_events(payload)
            else:
                d = payload["data"]
                raw = None
            origin_hub = (d.get("origin") or {}).get("unlocode")
            dest_hub = (d.get("destination") or {}).get("unlocode")
            raw = raw if raw is not None else [{
                "code": e.get("type"), "description": e.get("description"), "timestamp": e.get("occurred_at"),
                "actual": e.get("actual", True), "event_id": e.get("id"), "vessel": e.get("vessel"),
                "hub": (e.get("location") or {}).get("unlocode"), "name": (e.get("location") or {}).get("name"),
                "country": (e.get("location") or {}).get("country"),
                "lat": (e.get("location") or {}).get("lat"), "lon": (e.get("location") or {}).get("lon"),
            } for e in d["events"]]
            events, planned, milestones, _ = normalize_events(
                raw, source=self.id, now=now, destination_hub=dest_hub,
                carrier_code=carrier.code if carrier else None)
            eta = parse_ts(d.get("eta")) or planned
            vessel = _vessel(d.get("vessel")) or next((e.vessel for e in reversed(events) if e.vessel), None)
            code = (d.get("carrier") or {}).get("scac") or scac
            ref = carrier
            if ref is None and code and (c := find_carrier(code)):
                ref = c.ref()
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.id}: unusable payload", reason="bad_payload") from exc
        return TrackingSnapshot(
            provider=self.id, fetched_at=now, events=tuple(events), eta=eta,
            origin=location_of(origin_hub), origin_hub_id=origin_hub,
            destination=location_of(dest_hub), destination_hub_id=dest_hub,
            vessel=vessel, carrier=ref, milestones=milestones)


class HttpAwbProvider(_HttpBase):
    """Air waybill tracking: GET /v1/awb/{prefix-serial} (UNVERIFIED)."""

    id = "http_awb"
    kill_switch_env = "FF_TRACKING_AWB_DISABLED"

    async def track(self, reference: str, reference_type: ReferenceType, carrier: CarrierRef | None,
                    *, anchor: datetime, now: datetime) -> TrackingSnapshot:
        if reference_type is not ReferenceType.AWB:
            raise ProviderUnavailable(f"{self.id}: unsupported reference type", reason="unsupported")
        _check("awb", reference, self.id)
        payload = await self._get_json("/v1/awb/" + quote(reference, safe="-"))
        return self.parse(payload, now=now, carrier=carrier, reference=reference)

    def parse(self, payload: dict[str, Any], *, now: datetime, carrier: CarrierRef | None = None,
              reference: str = "") -> TrackingSnapshot:
        """UNVERIFIED shape: shipment.{origin,destination (IATA),estimated_arrival,
        events[{code (Cargo-IMP),time,station,flight,remarks}]}."""
        try:
            s = payload["shipment"]
            dest = s.get("destination")
            raw = [{"code": e.get("code"), "description": e.get("remarks"), "timestamp": e.get("time"),
                    "hub": e.get("station"), "flight": e.get("flight"), "event_id": e.get("id")}
                   for e in s["events"]]
            events, planned, milestones, _ = normalize_events(
                raw, source=self.id, now=now, destination_hub=dest)
            eta = parse_ts(s.get("estimated_arrival")) or planned
            flight = next((e.flight for e in reversed(events) if e.flight), None)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.id}: unusable payload", reason="bad_payload") from exc
        ref = carrier
        if ref is None and (c := carrier_for_awb_prefix(reference[:3])):
            ref = c.ref()
        return TrackingSnapshot(
            provider=self.id, fetched_at=now, events=tuple(events), eta=eta,
            origin=location_of(s.get("origin")), origin_hub_id=s.get("origin"),
            destination=location_of(dest), destination_hub_id=dest, flight=flight, carrier=ref,
            milestones=milestones)


class HttpVesselPositionProvider(_HttpBase):
    """AIS provider, official API only: GET /v1/vessels/{imo}/position -> position + ETA (UNVERIFIED).

    Never point this at a public AIS website; only a licensed/official API with a key.
    """

    id = "http_vessel"
    kill_switch_env = "FF_TRACKING_VESSEL_DISABLED"

    async def vessel_eta(self, imo: str, *, now: datetime) -> VesselEta | None:
        _check("imo", imo, self.id)
        payload = await self._get_json(f"/v1/vessels/{quote(imo, safe='')}/position")
        return self.parse(payload, imo=imo, now=now)

    def parse(self, payload: dict[str, Any], *, imo: str, now: datetime) -> VesselEta:
        """UNVERIFIED shape: vessel.{name,destination (UN/LOCODE),eta,position.{lat,lon,speed_kn}}."""
        try:
            v = payload["vessel"]
            pos = v.get("position") or {}
            point = GeoPoint(lat=float(pos["lat"]), lon=float(pos["lon"])) if "lat" in pos and "lon" in pos else None
            speed = float(pos["speed_kn"]) if pos.get("speed_kn") is not None else None
            return VesselEta(imo=imo, fetched_at=now, eta=parse_ts(v.get("eta")),
                             destination_locode=v.get("destination"), point=point, speed_knots=speed,
                             vessel_name=v.get("name"))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.id}: unusable payload", reason="bad_payload") from exc


class MockVesselEta:
    """Deterministic stand-in: ETA 10 days after ``now`` rounded to the hour, no position."""

    id = "mock_vessel"

    async def vessel_eta(self, imo: str, *, now: datetime) -> VesselEta | None:
        from datetime import timedelta
        return VesselEta(imo=imo, fetched_at=now,
                         eta=(now + timedelta(days=10)).replace(minute=0, second=0, microsecond=0))


__all__ = ["HttpAwbProvider", "HttpContainerProvider", "HttpVesselPositionProvider", "MockVesselEta",
           "resolve_location"]
