"""WebSocket proxy: /v1/ws/conversations/{id} -> messaging (same path upstream)."""

import asyncio
import contextlib
import logging
import uuid

from fastapi import APIRouter, WebSocket
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from ff_gateway.db import User
from ff_gateway.domain.errors import GatewayError

router = APIRouter()
log = logging.getLogger("ff_gateway")

WS_PREFIX = "/v1/ws/conversations/"
MAX_FRAME_BYTES = 1 << 20
HANDSHAKE_CODES = {401: 4401, 403: 4403, 429: 4429}


def _token(ws: WebSocket) -> str | None:
    scheme, _, tok = ws.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and tok.strip():
        return tok.strip()
    return ws.query_params.get("token") or None  # never logged


def _close_code(code: int | None) -> int:
    return code if code is not None and (code == 1000 or 3000 <= code <= 4999) else 1011


async def _reject(ws: WebSocket, code: int) -> None:
    await ws.accept()  # accept first so the client sees our close code, not a bare HTTP 403
    await ws.close(code=code)


@router.websocket("/v1/ws/{path:path}")
async def ws_proxy(ws: WebSocket, path: str) -> None:
    full = "/v1/ws/" + path
    if not full.startswith(WS_PREFIX) or len(full) == len(WS_PREFIX) or ".." in full.split("/"):
        return await _reject(ws, 4404)
    state = ws.app.state
    token = _token(ws)
    if token is None:
        return await _reject(ws, 4401)
    try:
        user_id = state.tokens.decode(token, "access")
    except GatewayError:
        return await _reject(ws, 4401)
    async with state.sessionmaker() as s:
        user = await s.get(User, user_id)
        claimed = (
            await s.scalar(
                select(User.supplier_id).where(
                    User.id == user_id, User.supplier_claim_status == "verified"
                )
            )
            if user
            else None
        )
    if user is None or not user.is_active:
        return await _reject(ws, 4401)

    headers = {"X-User-Id": user_id, "X-Request-Id": uuid.uuid4().hex}
    if claimed:  # verified claim from our DB, never from the client
        headers["X-Supplier-Id"] = claimed
    if state.settings.internal_token:
        headers["X-Internal-Token"] = state.settings.internal_token
    base = state.settings.upstream_map()["messaging"].rstrip("/")
    url = ("wss" if base.startswith("https") else "ws") + "://" + base.split("://", 1)[1] + full
    connect = getattr(state, "ws_connect", None) or ws_connect

    try:
        async with connect(
            url, additional_headers=headers, max_size=MAX_FRAME_BYTES, open_timeout=10
        ) as up:
            await ws.accept()

            async def client_to_up() -> None:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("text") is not None:
                        await up.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await up.send(msg["bytes"])

            async def up_to_client() -> None:
                async for frame in up:
                    if isinstance(frame, bytes):
                        await ws.send_bytes(frame)
                    else:
                        await ws.send_text(frame)

            tasks = [asyncio.create_task(client_to_up()), asyncio.create_task(up_to_client())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            code = _close_code(getattr(up, "close_code", None))
            with contextlib.suppress(Exception):
                await up.close()
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=code)
    except InvalidStatus as e:
        await _reject(ws, HANDSHAKE_CODES.get(e.response.status_code, 1011))
    except (OSError, TimeoutError, ConnectionClosed, WebSocketException):
        log.warning("messaging websocket upstream unavailable")
        if ws.application_state.name == "CONNECTING":
            await _reject(ws, 1011)
        else:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close(code=1011)
