"""Trust endpoints."""

from fastapi import APIRouter, Header, Query, Request

from ff_trust.adapters.base import AdapterDisabled
from ff_trust.api.errors import ApiError
from ff_trust.api.schemas import BatchOut, HistoryOut, ReportIn, ReportOut, TrustScoreOut
from ff_trust.domain.signals import SupplierSignals
from ff_trust.service import TrustService, report_out
from ff_trust.store import CapacityReached, RateLimited

router = APIRouter(prefix="/v1/trust")


def _svc(request: Request) -> TrustService:
    return request.app.state.service


@router.get("/suppliers:batch", response_model=BatchOut)
async def batch(request: Request, ids: str = Query(..., description="comma separated supplier ids")) -> BatchOut:
    svc = _svc(request)
    id_list = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))
    if not id_list:
        raise ApiError(422, "validation_error", "ids must not be empty")
    if len(id_list) > request.app.state.settings.max_batch:
        raise ApiError(422, "too_many_ids", f"at most {request.app.state.settings.max_batch} ids")
    items = []
    for sid in id_list:
        try:
            r = await svc.for_supplier(sid)
        except AdapterDisabled as e:
            raise ApiError(503, "adapter_disabled", str(e)) from e
        if r:
            items.append(r)
    return BatchOut(items=items)


@router.get("/suppliers/{supplier_id}", response_model=TrustScoreOut)
async def get_supplier(supplier_id: str, request: Request) -> TrustScoreOut:
    try:
        r = await _svc(request).for_supplier(supplier_id)
    except AdapterDisabled as e:
        raise ApiError(503, "adapter_disabled", str(e)) from e
    if r is None:
        raise ApiError(404, "supplier_not_found", f"No trust data for {supplier_id}")
    return r


@router.post("/evaluate", response_model=TrustScoreOut)
async def evaluate(signals: SupplierSignals, request: Request) -> TrustScoreOut:
    return _svc(request).evaluate(signals)


@router.get("/suppliers/{supplier_id}/history", response_model=HistoryOut)
async def history(supplier_id: str, request: Request) -> HistoryOut:
    try:
        r = await _svc(request).history(supplier_id)
    except AdapterDisabled as e:
        raise ApiError(503, "adapter_disabled", str(e)) from e
    if r is None:
        raise ApiError(404, "supplier_not_found", f"No trust data for {supplier_id}")
    return r


def _low_trust(request: Request, age: str | None, verified: str | None) -> bool:
    """Gateway-supplied account signals (X-Account-Age-Seconds / X-Email-Verified). Absent headers = unknown = normal
    behaviour (direct use, tests). Present but malformed fails closed to the low-trust bucket. Only the gateway can set
    them: with FF_INTERNAL_TOKEN set every request must carry the token, and the gateway strips client-supplied values."""
    if age is None and verified is None:
        return False
    if verified is not None and verified.strip().lower() not in ("1", "true"):
        return True
    if age is not None:
        try:
            return int(age.strip()) < request.app.state.settings.report_min_account_age_seconds
        except ValueError:
            return True
    return False


@router.post("/suppliers/{supplier_id}/report", response_model=ReportOut, status_code=201)
async def report(
    supplier_id: str, body: ReportIn, request: Request,
    x_user_id: str | None = Header(default=None),
    x_account_age_seconds: str | None = Header(default=None),
    x_email_verified: str | None = Header(default=None),
) -> ReportOut:  # fmt: skip
    """Buyer concern. Stored as pending_review; it never changes the score until a moderator accepts it."""
    uid = (x_user_id or "").strip()
    if not uid or len(uid) > 128:
        raise ApiError(401, "user_required", "X-User-Id header is required")
    svc = _svc(request)
    try:
        if await svc.adapter.get_signals(supplier_id) is None:
            raise ApiError(404, "supplier_not_found", f"No trust data for {supplier_id}")
    except AdapterDisabled as e:
        raise ApiError(503, "adapter_disabled", str(e)) from e
    try:
        return report_out(await svc.add_report(supplier_id, uid, body.type, body.text, _low_trust(request, x_account_age_seconds, x_email_verified)))
    except RateLimited as e:
        raise ApiError(429, "rate_limited", "Too many reports; try again later", {"retry_after_seconds": e.retry_after}, {"Retry-After": str(e.retry_after)}) from e
    except CapacityReached as e:
        raise ApiError(503, "capacity_reached", "Report store is full; try later") from e
