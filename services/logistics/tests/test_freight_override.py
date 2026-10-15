"""freight_override: an exact forwarder quote replaces the main-leg estimate (no network, mock FX/geo)."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ff_logistics.testing import req as base_req

FUTURE = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
PAST = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ov(**kw):
    return {"amount": "2500.00", "currency": "USD", "source": "forwarder_quote", "quote_id": "fqt_abc",
            "valid_until": FUTURE, **kw}


def body(override=None, **kw):
    d = base_req(**kw)
    if override is not None:
        d["freight_override"] = override
    return d


def main_leg(opt):
    return next(ln for ln in opt["lines"] if ln["stage"] == "main_leg")


def post(client, **kw):
    r = client.post("/v1/quotes/landed-cost", json=body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def sea40(q):
    return next(o for o in q["options"] if o["mode"] == "sea_fcl_40")


def test_valid_override_replaces_estimate(client):
    q = post(client, override=ov(), modes=["sea_fcl_40"])
    ln = main_leg(sea40(q))
    assert ln["estimate"] is False and ln["quoted"] is True and "range" not in ln
    assert ln["amount"] == {"amount": "2500.00", "currency": "USD"}
    assert ln["original_amount"] == {"amount": "2500.00", "currency": "USD"}
    assert "forwarder_quote fqt_abc" in ln["source"] and ln["as_of"]
    assert any("fqt_abc" in a and "exact price" in a for a in q["assumptions"])
    assert sea40(q)["sensitivity"]["freight"]["shock_pct"] == "0"
    base = main_leg(sea40(post(client, modes=["sea_fcl_40"])))
    assert base["estimate"] is True and base["amount"] != ln["amount"]


def test_currency_conversion_via_fx(client):
    # mock FX: 1 USD = 0.92 EUR = 7.20 CNY ; display currency USD
    q = post(client, override=ov(amount="1840.00", currency="EUR"), modes=["sea_fcl_40"])
    ln = main_leg(sea40(q))
    assert ln["amount"] == {"amount": "2000.00", "currency": "USD"}
    assert ln["original_amount"] == {"amount": "1840.00", "currency": "EUR"}
    assert Decimal(ln["fx_rate"]) == Decimal("1.0869565")  # EUR->USD, rounded
    # display currency == quote currency: exact, no USD round trip
    r = client.post("/v1/quotes/landed-cost", json={**body(override=ov(amount="1234.57", currency="CNY"),
                                                          modes=["sea_fcl_40"]), "display_currency": "CNY"})
    ln = main_leg(sea40(r.json()))
    assert ln["amount"] == {"amount": "1234.57", "currency": "CNY"} and ln["fx_rate"] == "1"


@pytest.mark.parametrize("override,why", [
    (ov(valid_until=PAST), "expired"),
    (ov(valid_until="not-a-date"), "malformed"),
    (ov(amount="abc"), "amount"),
    (ov(amount="-5"), "positive"),
    (ov(amount=True), "amount"),
    (ov(currency="usd"), "currency"),
    (ov(source="live_api"), "source"),
    (ov(quote_id=""), "quote_id"),
    (ov(mode_family="space"), "mode_family"),
    (ov(currency="XXX"), "FX"),
    ("garbage", "not an object"),
    ({}, "source"),
])
def test_invalid_override_ignored_with_note(client, override, why):
    q = post(client, override=override, modes=["sea_fcl_40"])
    ln = main_leg(sea40(q))
    assert ln["estimate"] is True and "quoted" not in ln
    notes = [a for a in q["assumptions"] if a.startswith("Forwarder freight quote ignored")]
    assert len(notes) == 1 and why.lower() in notes[0].lower()


def test_mode_family_scoping(client):
    q = post(client, override=ov(mode_family="air"), modes=["sea_fcl_40", "air"], kg=500, m3=2)
    assert main_leg(sea40(q))["estimate"] is True
    air = next(o for o in q["options"] if o["mode"] == "air")
    assert main_leg(air)["quoted"] is True
    q = post(client, override=ov(mode_family="rail"), modes=["sea_fcl_40"])
    assert main_leg(sea40(q))["estimate"] is True
    assert any("matched no option" in a for a in q["assumptions"])


def test_expiry_boundary_uses_clock(client, monkeypatch):
    from ff_logistics.domain import engine as eng
    t = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(eng, "_now", lambda: t)
    ok = post(client, override=ov(valid_until="2026-10-15T12:00:01Z"), modes=["sea_fcl_40"])
    assert main_leg(sea40(ok))["quoted"] is True
    gone = post(client, override=ov(valid_until="2026-10-15T12:00:00Z"), modes=["sea_fcl_40"])
    assert main_leg(sea40(gone))["estimate"] is True


def test_absent_override_unchanged(client):
    q = post(client, modes=["sea_fcl_40"])
    assert not any("Forwarder freight quote" in a for a in q["assumptions"])
    assert "quoted" not in main_leg(sea40(q))


def test_quoted_line_matches_common_schema(client):
    import json
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts/schemas/common.schema.json").read_text())
    props = schema["$defs"]["CostLine"]["properties"]
    assert props["quoted"]["type"] == "boolean" and "quoted" not in schema["$defs"]["CostLine"]["required"]
    ln = main_leg(sea40(post(client, override=ov(), modes=["sea_fcl_40"])))
    assert ln["quoted"] is True and set(ln) <= set(props)
