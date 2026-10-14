import hmac
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request

from ..adapters.carriers import list_carriers
from ..domain import hs as hs_domain
from ..domain.duties import load_json
from ..domain.engine import Engine
from ..domain.money import money
from ..errors import ApiError
from ..schemas import ConvertRequest, LandedCostRequest


def _auth(request: Request, x_internal_token: Annotated[str | None, Header()] = None):
    token = request.app.state.settings.internal_token
    if token and not hmac.compare_digest(x_internal_token or "", token):
        raise ApiError("unauthorized", "Missing or invalid internal token", 401)


router = APIRouter(prefix="/v1", dependencies=[Depends(_auth)])


@router.post("/quotes/landed-cost")
async def landed_cost(body: LandedCostRequest, request: Request):
    st = request.app.state
    try:
        return await Engine(st.geo, st.fx, st.freight, st.settings.freight_max_calls_per_quote).quote(body)
    except httpx.HTTPError as exc:
        raise ApiError("geo_unavailable", "Geo service unavailable", 502, {"reason": type(exc).__name__}) from exc


@router.get("/fx/rates")
async def fx_rates(request: Request, base: Annotated[str, Query(pattern=r"^[A-Z]{3}$")] = "USD"):
    t = await request.app.state.fx.table(base)
    return {"base": t.base, "timestamp": t.timestamp, "source": t.source,
            "rates": {k: format(v.normalize(), "f") for k, v in sorted(t.rates.items())}}


@router.post("/fx/convert")
async def fx_convert(body: ConvertRequest, request: Request):
    rate, t = await request.app.state.fx.rate(body.from_currency, body.to_currency)
    return {"amount": money(body.amount * rate, body.to_currency), "rate": format(rate.normalize(), "f"),
            "from": body.from_currency, "to": body.to_currency, "timestamp": t.timestamp, "source": t.source}


@router.get("/carriers")
async def carriers(origin_country: str | None = None, destination_country: str | None = None,
                   mode: str | None = None):
    items = list_carriers(origin_country, destination_country, mode)
    return {"items": items, "total": len(items)}


_HS_DISCLAIMER = "indicative, confirm with a customs broker"


@router.get("/hs/search")
async def hs_search(q: Annotated[str, Query(max_length=100)] = "", limit: Annotated[int, Query(ge=1, le=50)] = 10,
                    destination_country: Annotated[str, Query(pattern=r"^[A-Z]{2}$")] = "IQ"):
    if not q.strip():
        raise ApiError("validation_error", "q must not be empty", 422, {"field": "q"})
    duties = load_json("duties.json")
    items = [hs_domain.to_item(e, duties, destination_country) for e in hs_domain.search(q, limit)]
    return {"items": items, "total": len(items), "destination_country": destination_country,
            "disclaimer": _HS_DISCLAIMER}


@router.get("/hs/{code}")
async def hs_get(code: str, destination_country: Annotated[str, Query(pattern=r"^[A-Z]{2}$")] = "IQ"):
    if hs_domain.normalize_code(code) is None:
        raise ApiError("validation_error", "code must be 6 to 10 digits (dots allowed)", 422, {"field": "code"})
    entry = hs_domain.get(code)
    if entry is None:
        raise ApiError("not_found", f"HS code {code} not in the curated dataset", 404)
    return {**hs_domain.to_item(entry, load_json("duties.json"), destination_country),
            "destination_country": destination_country, "disclaimer": _HS_DISCLAIMER}
