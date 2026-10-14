"""Structured request logging + request-id propagation (self-contained; copied per service).

One JSON line per HTTP request on logger ``ff.request``: ts, level, service, request_id, method,
path (route template, never the raw URL), status, duration_ms and user_id when known.
Never logged: query strings, Authorization / token headers, bodies.
``FF_LOG_FORMAT=text`` switches to a human-readable line for local development.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
LOGGER_NAME = "ff.request"


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
            rest = " ".join(f"{k}={v}" for k, v in data.items() if v is not None)
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

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
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
