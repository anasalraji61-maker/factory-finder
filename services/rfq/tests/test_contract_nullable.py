"""Real responses must validate against contracts/openapi/rfq.yaml (target_price may be null)."""
import json
from pathlib import Path

import pytest
import yaml
from conftest import BUYER, new_request

jsonschema = pytest.importorskip("jsonschema")
referencing = pytest.importorskip("referencing")

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
COMMON_ID = "https://factory-finder.dev/schemas/common.schema.json"


def _validator(name: str):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    spec = yaml.safe_load((CONTRACTS / "openapi" / "rfq.yaml").read_text())
    common = json.loads((CONTRACTS / "schemas" / "common.schema.json").read_text())

    def rewrite(node):
        if isinstance(node, dict):
            return {k: (COMMON_ID + v.split("common.schema.json", 1)[1]
                        if k == "$ref" and isinstance(v, str) and "common.schema.json" in v
                        else rewrite(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [rewrite(x) for x in node]
        return node

    schemas = rewrite(spec["components"]["schemas"])
    root = {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/components/schemas/{name}", "components": {"schemas": schemas}}
    reg = Registry().with_resource(COMMON_ID, Resource.from_contents(common, DRAFT202012))
    return jsonschema.Draft202012Validator(root, registry=reg)


@pytest.mark.parametrize("with_price", [False, True])
def test_request_response_matches_contract(client, with_price):
    over = {"target_price": {"amount": "8", "currency": "USD"}} if with_price else {}
    body = new_request(client, **over)
    assert (body.get("target_price") is not None) == with_price
    _validator("Request").validate(body)
    got = client.get(f"/v1/requests/{body['id']}", headers=BUYER).json()
    _validator("Request").validate(got)


def test_null_target_price_is_in_response(client):
    body = new_request(client)
    assert "target_price" in body and body["target_price"] is None
