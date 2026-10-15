"""Pure-ASGI guards in front of every HTTP route: request body limits per route class, a body read deadline
(slowloris-style trickle uploads) and baseline response headers for gateway-owned responses."""

import asyncio
import contextlib
import json
import time

from ff_gateway.domain.routing import resolve_upstream

NO_STORE_PREFIXES = ("/v1/auth", "/v1/me", "/v1/ws-ticket", "/v1/admin")


class _TooLarge(Exception):
    pass


class _TooSlow(Exception):
    pass


def _json_error(status: int, code: str, message: str) -> tuple[list[tuple[bytes, bytes]], bytes]:
    body = json.dumps({"error": {"code": code, "message": message, "details": {}}}).encode()
    return [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())], body


class HttpGuardMiddleware:
    """Limits: media uploads (``/v1/media``) get ``max_body_bytes``; every other route class is JSON and gets
    ``min(max_body_bytes, json_max_body_bytes)``. Declared Content-Length is rejected up front; chunked bodies are counted
    while read. The body must arrive within ``body_read_timeout`` (media: ``media_body_read_timeout``) seconds in total."""

    def __init__(self, app, max_body_bytes: int, json_max_body_bytes: int, body_read_timeout: float,
                 media_body_read_timeout: float) -> None:  # fmt: skip
        self.app, self.media_max = app, max_body_bytes
        self.json_max = min(max_body_bytes, json_max_body_bytes)
        self.timeouts = (body_read_timeout, media_body_read_timeout)

    def _limits(self, path: str) -> tuple[int, float]:
        if resolve_upstream(path) == "media":
            return self.media_max, self.timeouts[1]
        return self.json_max, self.timeouts[0]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = rejected = False
        no_store = scope["path"].startswith(NO_STORE_PREFIXES)

        async def send_wrapper(message):
            nonlocal started
            if rejected:
                return  # our 413/408 is already out; swallow whatever the framework tries to say next
            if message["type"] == "http.response.start":
                started = True
                hdrs = list(message.get("headers", []))
                names = {k.lower() for k, _ in hdrs}
                if b"x-content-type-options" not in names:
                    hdrs.append((b"x-content-type-options", b"nosniff"))
                if no_store and b"cache-control" not in names:
                    hdrs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hdrs}
            await send(message)

        async def reject(status: int, code: str, text: str) -> None:
            nonlocal rejected
            h, b = _json_error(status, code, text)
            await send_wrapper({"type": "http.response.start", "status": status, "headers": h})
            await send_wrapper({"type": "http.response.body", "body": b})
            rejected = True

        # every method is guarded: the proxy buffers the body of GET/HEAD/OPTIONS requests too
        limit, timeout = self._limits(scope["path"])
        for k, v in scope["headers"]:
            if k == b"content-length":
                try:
                    declared = int(v)
                except ValueError:
                    return await reject(400, "bad_request", "Invalid Content-Length")
                if declared < 0:
                    return await reject(400, "bad_request", "Invalid Content-Length")
                if declared > limit:
                    return await reject(413, "payload_too_large", "Request body is too large")
        seen, deadline, done = 0, time.monotonic() + timeout, False

        async def guarded_receive():
            nonlocal seen, done
            if done:
                return await receive()
            try:
                msg = await asyncio.wait_for(receive(), max(0.001, deadline - time.monotonic()))
            except TimeoutError:
                if not started:  # the framework may turn an exception raised here into its own 400: answer first
                    await reject(408, "request_timeout", "Request body was not received in time")
                raise _TooSlow from None
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    if not started:
                        await reject(413, "payload_too_large", "Request body is too large")
                    raise _TooLarge
                done = not msg.get("more_body", False)
            return msg

        with contextlib.suppress(_TooLarge, _TooSlow):  # already answered in guarded_receive
            await self.app(scope, guarded_receive, send_wrapper)
