"""Real forwarder/application responses must validate against contracts/openapi/freight.yaml."""
import json
from pathlib import Path

import pytest
import yaml
from conftest import APP, make_forwarder, uh

jsonschema = pytest.importorskip("jsonschema")
referencing = pytest.importorskip("referencing")

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
COMMON_ID = "https://factory-finder.dev/schemas/common.schema.json"


def _validator(name: str):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    spec = yaml.safe_load((CONTRACTS / "openapi" / "freight.yaml").read_text())
    common = json.loads((CONTRACTS / "schemas" / "common.schema.json").read_text())

    def rewrite(node):
        if isinstance(node, dict):
            return {k: (COMMON_ID + v.split("common.schema.json", 1)[1]
                        if k == "$ref" and isinstance(v, str) and "common.schema.json" in v
                        else rewrite(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [rewrite(x) for x in node]
        return node

    root = {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/components/schemas/{name}", "components": {"schemas": rewrite(spec["components"]["schemas"])}}
    reg = Registry().with_resource(COMMON_ID, Resource.from_contents(common, DRAFT202012))
    return jsonschema.Draft202012Validator(root, registry=reg)


def test_forwarder_profile_matches_contract(client):
    make_forwarder(client, "fu1")
    prof = client.get("/v1/freight/forwarders/me", headers=uh("fu1")).json()
    assert "profile_completeness" in prof
    _validator("Forwarder").validate(prof)
    page = client.get("/v1/freight/forwarders", headers=uh("anyone")).json()
    assert page["items"]
    _validator("ForwarderPage").validate(page)


def test_application_attachments_and_duplicate_conflict(client):
    body = {**APP, "attachments": ["https://example.com/license.pdf"]}
    r = client.post("/v1/freight/applications", headers=uh("a1"), json=body)
    assert r.status_code == 201, r.text
    _validator("ApplicationCreate").validate(body)
    _validator("Application").validate(r.json())
    d = client.post("/v1/freight/applications", headers=uh("a2"), json=body)
    assert d.status_code == 409
    assert "duplicate_company" in json.dumps(d.json())
