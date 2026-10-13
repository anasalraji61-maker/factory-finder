from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request

from ..adapters.carriers import list_carriers
from ..domain.engine import Engine
from ..domain.money import money
from ..errors import ApiError
from ..schemas import ConvertRequest, LandedCostRequest


def _auth(request: Request, x_internal_token: Annotated[str | None, Header()] = None):
    token = request.app.state.settings.internal_token
    if token and x_internal_token != token:
        raise ApiError("unauthorized", "Missing or invalid internal token", 401)


router = APIRouter(prefix="/v1", dependencies=[Depends(_auth)])


@router.post("/quotes/landed-cost")
async def landed_cost(body: LandedCostRequest, request: Request):
    st = request.app.state
    try:
        return await Engine(st.geo, st.fx).quote(body)
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
