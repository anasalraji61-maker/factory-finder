"""Trust endpoints."""

from fastapi import APIRouter, Query, Request

from ff_trust.adapters.base import AdapterDisabled
from ff_trust.api.errors import ApiError
from ff_trust.api.schemas import BatchOut, TrustScoreOut
from ff_trust.domain.signals import SupplierSignals
from ff_trust.service import TrustService

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
