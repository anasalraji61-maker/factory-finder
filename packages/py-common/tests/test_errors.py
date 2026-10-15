import pytest

from ff_common.errors import code_for_status, error_body, is_error_body


def test_envelope_shape():
    b = error_body("not_found", "missing", {"id": "x"})
    assert b == {"error": {"code": "not_found", "message": "missing", "details": {"id": "x"}}}
    assert is_error_body(b)


def test_details_default_and_copied():
    d = {"a": 1}
    b = error_body("c", "m", d)
    d["a"] = 2
    assert b["error"]["details"] == {"a": 1}
    assert error_body("c", "m")["error"]["details"] == {}


def test_required_fields():
    with pytest.raises(ValueError):
        error_body("", "m")
    with pytest.raises(ValueError):
        error_body("c", "")


@pytest.mark.parametrize("bad", [None, {}, {"error": "x"}, {"error": {"code": 1, "message": "m"}},
                                 {"error": {"code": "c", "message": "m", "details": []}}])
def test_is_error_body_rejects(bad):
    assert not is_error_body(bad)


def test_status_codes():
    assert code_for_status(404) == "not_found"
    assert code_for_status(502) == "internal_error"
    assert code_for_status(418) == "error"


def test_matches_contract_schema():
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[3] / "contracts/schemas/common.schema.json"
    err = json.loads(p.read_text())["$defs"]["Error"]
    assert set(err["required"]) == {"error"}
    assert set(err["properties"]["error"]["required"]) <= set(error_body("c", "m")["error"])
