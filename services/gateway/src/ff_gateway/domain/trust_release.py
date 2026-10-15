"""Best-effort call to trust: withdraw/hide a supplier's verification documents once a claim is released."""

import asyncio
import logging

import httpx

log = logging.getLogger("ff_gateway.trust_release")
RELEASE_TIMEOUT_SECONDS = 3.0


async def release_supplier(app, request, supplier_id: str | None, reason: str, reviewer: str = "admin") -> bool:
    """POST trust's admin release for the OLD supplier id. Never raises; failures are logged (status/exception class only, no secrets)."""
    s = app.state.settings
    if not supplier_id or not s.trust_admin_token:
        return False
    from ff_gateway.api.deps import internal_headers  # local: avoid import cycle

    headers = {**internal_headers(request, "admin"), "X-Admin-Token": s.trust_admin_token, "X-Reviewer": reviewer}
    url = s.upstream_map()["trust"].rstrip("/") + f"/v1/admin/trust/verification/suppliers/{supplier_id}/release"
    try:
        r = await asyncio.wait_for(
            app.state.http.post(url, headers=headers, json={"reason": reason[:500]}), RELEASE_TIMEOUT_SECONDS
        )
        if r.status_code == 200:
            return True
        log.warning("trust release failed for supplier %s: status %s", supplier_id, r.status_code)
    except (httpx.HTTPError, TimeoutError) as e:
        log.warning("trust release failed for supplier %s: %s", supplier_id, type(e).__name__)
    except Exception as e:  # noqa: BLE001 - never block the user-facing action
        log.warning("trust release failed for supplier %s: %s", supplier_id, type(e).__name__)
    return False
