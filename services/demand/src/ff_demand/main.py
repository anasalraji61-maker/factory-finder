"""FastAPI app factory. ``app = create_app()`` for uvicorn."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ff_demand.config import Settings
from ff_demand.errors import ApiError, NotFound, Unauthenticated
from ff_demand.service import DemandService
from ff_demand.signals import MockSignalSource, RawSignal, SignalSource
from ff_demand.sourcing import HttpSourcingClient, MockSourcingClient, SourcingClient
from ff_demand.store import Store

VERSION = "0.1.0"
router = APIRouter(prefix="/v1")


def svc(request: Request) -> DemandService:
    return request.app.state.service


def admin(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> str:
    expected = request.app.state.settings.internal_token_value
    if expected is not None and not hmac.compare_digest(x_internal_token or "", expected):
        raise Unauthenticated("Invalid internal token")
    if not x_user_id or len(x_user_id) > 64:
        raise Unauthenticated("X-User-Id header is required")
    return x_user_id


Actor = Annotated[str, Depends(admin)]
Service = Annotated[DemandService, Depends(svc)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalIn(_Body):
    text: str = Field(min_length=3, max_length=5000)
    url: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="manual", max_length=40)
    language: str | None = Field(default=None, pattern="^(ar|en)$")


class ApproveIn(_Body):
    text: str | None = Field(default=None, max_length=5000)


class RejectIn(_Body):
    reason: str | None = Field(default=None, max_length=500)


class PublishedIn(_Body):
    published_url: str | None = Field(default=None, max_length=1000)


class OutcomeIn(_Body):
    outcome: str
    note: str | None = Field(default=None, max_length=500)


def _result(r: dict) -> dict:
    return {"signal": r["signal"], "draft": r["draft"], "duplicate": r["duplicate"]}


@router.post("/signals")
async def import_signal(body: SignalIn, s: Service, _: Actor, response: Response):
    r = await s.import_signal(RawSignal(body.text, body.url, body.source), body.language)
    response.status_code = 201 if r["created"] else 200
    return _result(r)


@router.post("/signals/poll")
async def poll(s: Service, _: Actor):
    return {"items": [_result(r) for r in await s.poll()]}


@router.get("/signals")
async def list_signals(s: Service, _: Actor):
    items = await s.store.list_signals()
    return {"items": items, "total": len(items)}


@router.get("/signals/{sid}")
async def get_signal(sid: str, s: Service, _: Actor):
    sig = await s.store.get_signal(sid)
    if not sig:
        raise NotFound("Signal not found")
    return sig


@router.get("/drafts")
async def list_drafts(s: Service, _: Actor, status: str | None = None):
    items = await s.store.list_drafts(status)
    return {"items": items, "total": len(items)}


@router.get("/drafts/{did}")
async def get_draft(did: str, s: Service, _: Actor):
    return await s.get_draft(did)


@router.post("/drafts/{did}/approve")
async def approve(did: str, s: Service, actor: Actor, body: ApproveIn | None = None):
    return await s.approve(did, actor, body.text if body else None)


@router.post("/drafts/{did}/reject")
async def reject(did: str, s: Service, actor: Actor, body: RejectIn | None = None):
    return await s.reject(did, actor, body.reason if body else None)


@router.post("/drafts/{did}/mark-published")
async def mark_published(did: str, s: Service, actor: Actor, body: PublishedIn | None = None):
    return await s.mark_published(did, actor, body.published_url if body else None)


@router.post("/drafts/{did}/outcome")
async def outcome(did: str, body: OutcomeIn, s: Service, actor: Actor):
    return await s.outcome(did, actor, body.outcome, body.note)


@router.get("/quota")
async def quota(s: Service, _: Actor):
    return await s.quota()


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}}, status_code=status
    )


def create_app(
    settings: Settings | None = None,
    *,
    sourcing: SourcingClient | None = None,
    source: SignalSource | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.database_url)
    if sourcing is None:
        sourcing = (
            MockSourcingClient()
            if settings.use_mock_sourcing
            else HttpSourcingClient(settings.sourcing_base_url, settings.sourcing_timeout_seconds)
        )
    if source is None and settings.signal_source == "mock":
        source = MockSignalSource()
    service = DemandService(store, sourcing, settings, source)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await store.create_all()
        yield
        if hasattr(sourcing, "aclose"):
            await sourcing.aclose()
        await store.dispose()

    app = FastAPI(title="Factory Finder demand", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "Request validation failed", {"errors": errs})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return _error(
            exc.status_code,
            "not_found" if exc.status_code == 404 else "http_error",
            str(exc.detail),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "demand", "version": VERSION}

    app.include_router(router)
    return app


app = create_app()
