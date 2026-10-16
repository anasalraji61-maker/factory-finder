"""Structured request logging + request-id propagation (self-contained; copied per service).

One JSON line per HTTP request on logger ``ff.request``: ts, level, service, request_id, method,
path (route template, never the raw URL), status, duration_ms and user_id when known.
Never logged: query strings, Authorization / token headers, bodies.
``FF_LOG_FORMAT=text`` switches to a human-readable line for local development.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
LOGGER_NAME = "ff.request"
_CTRL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")


# --------------------------------------------------------------------------------------------
# Prometheus text metrics (dependency-free, per process). GET /metrics is answered by the
# outermost middleware, only when FF_<SVC>_METRICS=1, and only with the internal token (when
# FF_INTERNAL_TOKEN is set; with no token it is served only outside FF_ENV=production).
# Labels: service, method (fixed set), route template, status class. Never user input.
# --------------------------------------------------------------------------------------------
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_MAX_SERIES = 500
_STARTED = time.time()
_LOCK = threading.Lock()
_SERIES: dict[tuple[str, str, str], list] = {}  # (method, route, class) -> [count, sum, buckets]


def _label(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_./{}<>:\-]', "_", value)[:120]


def record_request(method: str, route: str, status: int, seconds: float) -> None:
    key = (
        method if method in _METHODS else "OTHER",
        _label(route),
        f"{status // 100}xx" if 100 <= status < 600 else "other",
    )
    with _LOCK:
        if key not in _SERIES and len(_SERIES) >= _MAX_SERIES:
            key = (key[0], "<other>", key[2])
        s = _SERIES.setdefault(key, [0, 0.0, [0] * len(_BUCKETS)])
        s[0] += 1
        s[1] += seconds
        for i, b in enumerate(_BUCKETS):
            if seconds <= b:
                s[2][i] += 1


def reset_metrics() -> None:
    with _LOCK:
        _SERIES.clear()


def render_metrics(service: str) -> str:
    out = [
        "# HELP ff_http_requests_total HTTP requests by route template and status class.",
        "# TYPE ff_http_requests_total counter",
    ]
    with _LOCK:
        items = sorted((k, [v[0], v[1], list(v[2])]) for k, v in _SERIES.items())
    for (m, r, c), (n, _, _) in items:
        lbl = f'service="{service}",method="{m}",route="{r}",status_class="{c}"'
        out.append(f"ff_http_requests_total{{{lbl}}} {n}")
    out += [
        "# HELP ff_http_request_duration_seconds Request latency histogram.",
        "# TYPE ff_http_request_duration_seconds histogram",
    ]
    for (m, r, c), (n, total, buckets) in items:
        lbl = f'service="{service}",method="{m}",route="{r}",status_class="{c}"'
        for b, v in zip(_BUCKETS, buckets, strict=True):
            out.append(f'ff_http_request_duration_seconds_bucket{{{lbl},le="{b}"}} {v}')
        out.append(f'ff_http_request_duration_seconds_bucket{{{lbl},le="+Inf"}} {n}')
        out.append(f"ff_http_request_duration_seconds_sum{{{lbl}}} {total:.6f}")
        out.append(f"ff_http_request_duration_seconds_count{{{lbl}}} {n}")
    out += [
        "# HELP ff_process_uptime_seconds Seconds since this process imported the service.",
        "# TYPE ff_process_uptime_seconds gauge",
        f'ff_process_uptime_seconds{{service="{service}"}} {time.time() - _STARTED:.1f}',
    ]
    return "\n".join(out) + "\n"


def metrics_enabled(service: str) -> bool:
    return os.environ.get(f"FF_{service.upper()}_METRICS", "").strip() == "1"


def _metrics_allowed(headers: dict[str, str]) -> bool | None:
    """True = serve, False = wrong or missing token (401), None = production without token (404)."""
    token = os.environ.get("FF_INTERNAL_TOKEN", "")
    if not token:
        return None if os.environ.get("FF_ENV", "").strip().lower() == "production" else True
    return hmac.compare_digest(headers.get("x-internal-token", "").encode(), token.encode())


async def _send_plain(send, status: int, body: bytes, ctype: str) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store")]})  # fmt: skip
    await send({"type": "http.response.body", "body": body})


def sanitize_id(value: str | None) -> str | None:
    """Accept a caller-supplied id only if short and made of safe characters."""
    return value if value and _ID_RE.match(value) else None


class _Stdout:
    def write(self, s: str) -> int:
        return sys.stdout.write(s)

    def flush(self) -> None:
        sys.stdout.flush()


class _Formatter(logging.Formatter):
    def __init__(self, fmt: str) -> None:
        super().__init__()
        self.fmt = fmt

    def format(self, record: logging.LogRecord) -> str:
        data = getattr(record, "ff", None) or {"msg": record.getMessage()}
        if self.fmt == "text":
            # strip CR/LF/control chars so a value cannot forge extra log lines
            rest = " ".join(
                f"{k}={_CTRL.sub(' ', str(v))}" for k, v in data.items() if v is not None
            )
            return f"{datetime.now(UTC).isoformat(timespec='seconds')} {record.levelname} {rest}"
        return json.dumps(
            {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "level": record.levelname,
             **{k: v for k, v in data.items() if v is not None}},
            separators=(",", ":"), ensure_ascii=False,
        )  # fmt: skip


def configure_logging() -> logging.Logger:
    log = logging.getLogger(LOGGER_NAME)
    fmt = "text" if os.environ.get("FF_LOG_FORMAT", "json").strip().lower() == "text" else "json"
    if not any(getattr(h, "_ff", False) for h in log.handlers):
        h = logging.StreamHandler(_Stdout())  # type: ignore[arg-type]
        h._ff = True  # type: ignore[attr-defined]
        log.addHandler(h)
        log.propagate = False
    for h in log.handlers:
        if getattr(h, "_ff", False):
            h.setFormatter(_Formatter(fmt))
    log.setLevel(logging.INFO)
    return log


class RequestLogMiddleware:
    """Pure ASGI middleware (passes websocket/lifespan through untouched)."""

    def __init__(self, app, service: str, trust_user_header: bool = True) -> None:
        self.app, self.service, self.trust_user_header = app, service, trust_user_header
        self.log = configure_logging()

    async def _metrics(self, scope, send):
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        allowed = _metrics_allowed(headers) if metrics_enabled(self.service) else None
        if allowed is None:
            return await _send_plain(send, 404, b'{"detail":"Not Found"}', "application/json")
        if not allowed:
            msg = b'{"error":{"code":"invalid_internal_token","message":"invalid token"}}'
            return await _send_plain(send, 401, msg, "application/json")
        body = render_metrics(self.service).encode()
        ctype = "text/plain; version=0.0.4; charset=utf-8"
        return await _send_plain(send, 200, body, ctype)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] == "GET" and scope.get("path") == "/metrics":
            return await self._metrics(scope, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        rid = sanitize_id(headers.get("x-request-id")) or uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = rid
        status = 500
        start = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                old = message.get("headers", [])
                hdrs = [(k, v) for k, v in old if k.lower() != b"x-request-id"]
                hdrs.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = state.get("path_template") or getattr(route, "path", None) or "<unmatched>"
            uid = state.get("user_id") or (
                sanitize_id(headers.get("x-user-id")) if self.trust_user_header else None
            )
            elapsed = time.perf_counter() - start
            record_request(scope["method"], path, status, elapsed)
            self.log.info(
                "request",
                extra={"ff": {
                    "service": self.service, "request_id": rid, "method": scope["method"],
                    "path": path, "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2), "user_id": uid,
                }},
            )  # fmt: skip


def install_observability(app: FastAPI, service: str, *, trust_user_header: bool = True) -> None:
    app.add_middleware(RequestLogMiddleware, service=service, trust_user_header=trust_user_header)


async def db_ready(engine) -> bool:
    """True when a trivial query succeeds on the async SQLAlchemy engine (never raises)."""
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def ready_response(
    service: str, checks: dict[str, bool], *, ok: bool | None = None
) -> JSONResponse:
    """200 ready when ok (default: all checks pass), else 503 unavailable."""
    ok = all(checks.values()) if ok is None else ok
    return JSONResponse(
        {"status": "ready" if ok else "unavailable", "service": service, "checks": checks},
        status_code=200 if ok else 503,
    )
