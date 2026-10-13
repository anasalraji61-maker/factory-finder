import httpx
import pytest
import respx

from ff_rfq.clients.sourcing import HttpSourcingClient
from ff_rfq.domain.errors import UpstreamUnavailable


@respx.mock
async def test_http_client_params_and_parse():
    route = respx.get("http://src/v1/search").mock(return_value=httpx.Response(200, json={"items": [{"id": "lst_1"}]}))
    items = await HttpSourcingClient("http://src").search("pump", "product", "used", 3)
    assert items == [{"id": "lst_1"}]
    q = route.calls[0].request.url.params
    assert q["q"] == "pump" and q["kind"] == "product" and q["condition"] == "used" and q["page_size"] == "3"


@respx.mock
async def test_http_client_failure_maps_to_upstream_unavailable():
    respx.get("http://src/v1/search").mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamUnavailable):
        await HttpSourcingClient("http://src").search("pump", None, None, 3)
