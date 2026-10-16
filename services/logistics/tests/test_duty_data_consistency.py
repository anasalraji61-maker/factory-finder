"""Internal-consistency audit of data/duties.json (offline; no claim of official accuracy)."""
import json
import re
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "src" / "ff_logistics" / "data"
TABLE = json.loads((DATA / "duties.json").read_text(encoding="utf-8"))
COUNTRIES = TABLE["countries"]
ALLOWED_CONF = {"low", "medium", "unverified", "estimate"}
# Officially assigned ISO 3166-1 alpha-2 codes for every destination currently in the table.
ISO_2 = set(
    ["AE", "AR", "AT", "AU", "AZ", "BD", "BE", "BG", "BH", "BR", "CA", "CH", "CL", "CN", "CO", "CZ", "DE", "DZ", "EG", "ES", "FR", "GB", "GE", "GH", "GR", "HK", "HU", "ID", "IN", "IQ", "IR", "IT", "JO", "JP", "KE", "KR", "KW", "KZ", "LB", "LK", "LY", "MA", "MX", "MY", "NG", "NL", "OM", "PE", "PH", "PK", "PL", "PT", "QA", "RO", "RS", "RU", "SA", "SE", "SG", "SN", "SY", "TH", "TN", "TR", "TW", "UA", "US", "UZ", "VN", "ZA"]
)
EU = ["AT", "BE", "BG", "CZ", "DE", "ES", "FR", "GR", "HU", "IT", "NL", "PL", "PT", "RO", "SE"]


def test_iso_codes():
    for c in COUNTRIES:
        assert re.fullmatch(r"[A-Z]{2}", c), c
        assert c in ISO_2, f"{c} is not a known ISO-3166 alpha-2 code"


@pytest.mark.parametrize("c", ["IQ", "AE", "SA", "TR", "US", "CN", *EU])
def test_required_countries_present(c):
    assert c in COUNTRIES


def test_vat_in_range():
    for c, v in COUNTRIES.items():
        assert 0 <= v["vat_pct"] <= 40, c
        lo, hi = v["vat_range_pct"]
        assert 0 <= lo <= v["vat_pct"] <= hi <= 40, c


def test_duty_ranges_bracket_default():
    for c, v in COUNTRIES.items():
        lo, hi = v["duty_range_pct"]
        assert 0 <= lo <= v["default_duty_pct"] <= hi <= 150, c


def test_de_minimis_labelled():
    seen = 0
    for c, v in COUNTRIES.items():
        dm = v.get("de_minimis")
        if not dm:
            continue
        seen += 1
        assert re.fullmatch(r"[A-Z]{3}", dm["currency"]), c
        assert dm["threshold"] >= 0, c
        assert dm["as_of"] and dm["source"] and dm["status"], c
        assert dm["confidence"] in ALLOWED_CONF, c
    assert seen >= 3


def test_every_entry_labelled_estimate():
    assert TABLE["as_of"] and "verify" in TABLE["label"]
    for c, v in COUNTRIES.items():
        assert v["source"].strip(), c
        assert re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", v["as_of"]), c
        assert v["confidence"] in ALLOWED_CONF, c
        assert v["confidence"] != "high", c
        assert "indicative" in v["label"], c
        assert "official" not in v["source"].lower().replace("official tariff schedule", ""), c


def test_chapter_rules_consistent():
    cats = TABLE["category_chapters"]
    for name, ch in cats.items():
        assert re.fullmatch(r"\d{2}", ch), name
    for c, v in COUNTRIES.items():
        keys = list(v["chapters"])
        assert len(keys) == len(set(keys))  # JSON would silently drop dupes; guard list form
        lo, hi = v["duty_range_pct"]
        for ch, rate in v["chapters"].items():
            assert re.fullmatch(r"\d{2}", ch) and 1 <= int(ch) <= 97, (c, ch)
            assert 0 <= rate <= 150, (c, ch)
            # a chapter rate must not contradict the country's stated range
            assert lo <= rate <= hi, f"{c} ch{ch}={rate} outside range {lo}-{hi}"


def test_no_duplicate_json_keys():
    def hook(pairs):
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"
        return dict(pairs)

    json.loads((DATA / "duties.json").read_text(encoding="utf-8"), object_pairs_hook=hook)


def test_verified_vat_items_have_official_source():
    ok = {"SA", "GB", "EG", "DE", "AE"}
    got = {c for c, v in COUNTRIES.items() if "vat_verification" in v}
    assert got == ok
    for c in got:
        vv = COUNTRIES[c]["vat_verification"]
        assert vv["status"] == "verified" and vv["vat_pct"] == COUNTRIES[c]["vat_pct"], c
        assert re.fullmatch(r"https://[\w.-]+\.(gov\.\w\w|gov|de)/\S+", vv["source_url"]), c
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", vv["checked"]), c
        assert COUNTRIES[c]["confidence"] != "high"  # duty rates still unverified


def test_us_de_minimis_verification():
    v = COUNTRIES["US"]["de_minimis"]["verification"]
    assert v["status"] == "verified" and "whitehouse.gov" in v["source_url"]
    assert COUNTRIES["US"]["de_minimis"]["status"] == "suspended"
