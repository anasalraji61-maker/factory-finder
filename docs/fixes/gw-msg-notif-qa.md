# QA: gateway / messaging / notifications / assistant (2026-10)

Open items (not fixed in place, need owner/contract decision):

1. messaging + notifications return 403 (not 404) for another user's resource id (conversation, watch, alert, device). IDs are random (ULID / 96-bit) so enumeration risk is low; the contract documents 403, so changing to 404 needs a contract revision.
2. messaging WebSocket access is checked once at connect. A later block does not close live sockets (blocked party cannot send, and the blocker's own socket only gets traffic they could already see). The gateway now bounds socket life (`FF_GATEWAY_WS_MAX_SESSION_SECONDS`, default 4h, close 1001) so revoked/deactivated users cannot hold sockets indefinitely; per-event revocation would need a gateway<->messaging channel.
3. messaging typing throttle and in-memory hub are per process; multi-replica needs Redis fan-out (already a known limitation).
