from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ff_assistant import __version__
from ff_assistant.api.routes import internal, router
from ff_assistant.clients import Clients, build_http_clients, build_mock_clients
from ff_assistant.config import Settings, get_settings
from ff_assistant.llm import LlmClient, build_llm
from ff_assistant.obs import install_observability, ready_response
from ff_assistant.quota import BurstLimiter, DailyQuota
from ff_assistant.ratelimit import make_redis_client
from ff_assistant.service import Assistant


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}})


def _docs_kwargs() -> dict[str, None]:
    """FF_ENV=production: no /docs, /redoc or /openapi.json (the schema lives in contracts/)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def create_app(settings: Settings | None = None, clients: Clients | None = None, llm: LlmClient | None = None,
               quota: DailyQuota | None = None) -> FastAPI:
    s = settings or get_settings()
    _require_production_token(s.internal_token.get_secret_value() if s.internal_token else os.environ.get("FF_INTERNAL_TOKEN"))
    c = clients or (build_mock_clients() if s.clients == "mock" else build_http_clients(s))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        for client in (c.sourcing, c.logistics, c.trust, c.tracking, c.deals, app.state.assistant.llm):
            close = getattr(client, "aclose", None)
            if close:
                await close()

    app = FastAPI(**_docs_kwargs(), title="Factory Finder - assistant", version=__version__, lifespan=lifespan)
    app.state.assistant = Assistant(c, s, llm=llm if llm is not None else build_llm(s))

    app.state.settings = s
    app.state.burst = BurstLimiter(s.rate_limit_per_minute, s.anon_rate_limit_per_minute)
    app.state.quota = quota or DailyQuota(s.quota_per_day, s.anon_quota_per_day, redis=make_redis_client(s.redis_url))

    @app.middleware("http")
    async def internal_token(request: Request, call_next):
        guarded = s.internal_token and request.url.path.startswith("/v1/")
        if guarded and not hmac.compare_digest((request.headers.get("X-Internal-Token", "")).encode(), (s.internal_token.get_secret_value()).encode()):
            if request.url.path.startswith("/v1/internal/users/"):  # account export/erasure: invisible to non-internal callers
                return _error(404, "not_found", "not found")
            return _error(401, "unauthorized", "invalid internal token")
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "invalid request", {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "assistant", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("assistant", {})

    app.include_router(router)
    app.include_router(internal)
    install_observability(app, "assistant")
    return app


app = create_app()
