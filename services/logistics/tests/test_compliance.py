import re
from pathlib import Path

import pytest

from ff_logistics.domain import compliance as comp
from ff_logistics.domain.incoterms import BUYER_STAGES, CUSTOMS_ADDS
from ff_logistics.testing import req

DATA = comp.data()
ALL_PROFILES = {**DATA["countries"], "ZZ": DATA["default_country"]}
CONF = {"low", "medium", "high"}
REQS = {"required", "conditional", "recommended"}
STAGES_OK = {"pre_shipment", "shipping", "clearance"}
SEVS = {"prohibited", "licence_required", "restricted", "enhanced_scrutiny"}
ARABIC = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")
PRIORITY = ["IQ", "SA", "AE", "KW", "QA", "OM", "BH", "TR", "JO", "EG", "DE", "FR", "US"]


def post(client, **kw):
    body = {"destination_country": "IQ", "origin_country": "CN"}
    body.update(kw)
    r = client.post("/v1/compliance/checklist", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def ids(b, key="documents"):
    return {x["id"] for x in b[key]}


# ------------------------------------------------------------------ data shape
@pytest.mark.parametrize("pid", sorted(ALL_PROFILES))
def test_country_entry_shape(pid):
    p = ALL_PROFILES[pid]
    for k in ("name_en", "name_ar", "authority_en", "authority_ar", "customs_system", "notes_en", "notes_ar", "source"):
        assert isinstance(p[k], str) and p[k].strip(), k
    assert p["as_of"] == "2026-10"
    assert p["confidence"] in CONF
    assert p["customs_value_basis"] in ("CIF", "FOB") and p["ddp_feasible"] in ("rarely", "possible")
    assert isinstance(p["covered"], bool) and isinstance(p["priority"], int)
    assert p["documents"] and p["restrictions"]
    for fam in ("sea", "air", "road", "rail"):
        c = p["clearance_days"][fam]
        assert 0 <= c["min"] <= c["max"] <= 90, fam
    seen = set()
    for d in p["documents"]:
        assert d["requirement"] in REQS and d["id"] not in seen
        seen.add(d["id"])
        assert d["groups"] == "*" or (d["groups"] and set(d["groups"]) <= set(DATA["groups"])), d["id"]
        assert d.get("stage", "shipping") in STAGES_OK
        assert d.get("confidence", "low") in CONF
        if "lead_days" in d:
            assert 0 <= d["lead_days"]["min"] <= d["lead_days"]["max"]
        for pref in d.get("hs_prefixes", []):
            assert pref.isdigit() and 2 <= len(pref) <= 10
        # a document must resolve to a name and note in both languages (own or library)
        lib = DATA["documents"].get(d["id"], {})
        for f in ("name_en", "name_ar"):
            assert d.get(f) or lib.get(f), (pid, d["id"], f)
    seen = set()
    for r in p["restrictions"]:
        assert r["severity"] in SEVS and r["id"] not in seen
        seen.add(r["id"])
        assert r["text_en"].strip() and r["text_ar"].strip()
        assert r.get("confidence", "low") in CONF
        assert set(r.get("groups", [])) <= set(DATA["groups"])
        for pref in r.get("hs_prefixes", []):
            assert pref.isdigit()
        for o in r.get("origins", []):
            assert re.fullmatch(r"[A-Z]{2}", o)
        assert r.get("condition", "used") in ("new", "used")
    if "members" in p:
        assert all(re.fullmatch(r"[A-Z]{2}", m) for m in p["members"])


def test_priority_destinations_covered():
    for c in PRIORITY:
        profile, pid = comp.profile_for(c)
        assert pid != "ZZ" and profile["covered"], c
    assert comp.profile_for("DE")[1] == "EU" and comp.profile_for("FR")[1] == "EU"
    assert comp.profile_for("ZW")[1] == "ZZ"


def test_global_library_shape():
    assert DATA["as_of"] == "2026-10" and DATA["indicative"] is True
    assert "licensed customs broker" in DATA["label_en"]
    assert DATA["label_ar"] and ARABIC.search(DATA["label_ar"])
    for did, d in DATA["documents"].items():
        assert d["stage"] in STAGES_OK and d["name_en"] and d["name_ar"] and d["note_en"] and d["note_ar"], did
    for s in DATA["base_documents"] + DATA["group_documents"] + DATA["dangerous_goods_documents"]:
        assert s["id"] in DATA["documents"] and s["requirement"] in REQS
    for fam in ("sea", "air", "road", "rail"):
        assert DATA["transport_documents"][fam] in DATA["documents"]
    # every HS chapter 01-97 (77 is reserved) belongs to exactly one product group
    owners: dict[str, list[str]] = {}
    for g, v in DATA["groups"].items():
        assert v["name_en"] and v["name_ar"]
        for ch in v["chapters"]:
            owners.setdefault(ch, []).append(g)
    for i in range(1, 98):
        ch = f"{i:02d}"
        if ch == "77":
            continue
        assert len(owners.get(ch, [])) == 1, ch
    assert all(g in DATA["groups"] for g in DATA["category_aliases"].values())


# ------------------------------------------------------------------ ar + en parity
def _walk(node, path=""):
    if isinstance(node, dict):
        keys = set(node)
        for k in keys:
            if k.endswith("_en"):
                assert k[:-3] + "_ar" in keys, f"{path}.{k} has no _ar twin"
            if k.endswith("_ar"):
                assert k[:-3] + "_en" in keys, f"{path}.{k} has no _en twin"
        for k, v in node.items():
            if k.endswith("_ar") and isinstance(v, str):
                assert v.strip() and ARABIC.search(v), f"{path}.{k} is empty or not Arabic"
            if k.endswith("_en") and isinstance(v, str):
                assert v.strip() and LATIN.search(v), f"{path}.{k} is empty or not English"
            _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]")


def test_data_ar_en_parity():
    _walk(DATA)


def test_output_ar_en_parity_for_every_country_and_group():
    for dest in sorted(set(comp._member_profile()) | {"ZW"}):  # every profile id + every EU member + unknown
        for g in DATA["groups"]:
            hs = DATA["groups"][g]["chapters"][0] + "0000"
            for mode in ("sea_fcl_40", "air", "road"):
                out = comp.checklist(dest, hs, None, "CN", "EXW", mode, "used", True)
                _walk(out, f"{dest}/{g}/{mode}")
                for d in out["documents"]:
                    assert d["name_en"] and d["name_ar"] and d["note_en"] and d["note_ar"], (dest, d["id"])


# ------------------------------------------------------------------ incoterms
@pytest.mark.parametrize("term", list(BUYER_STAGES))
def test_incoterm_legs_tie_to_landed_cost_table(term):
    info = comp.incoterm_info(term)
    assert [x["stage"] for x in info["legs"]] == comp.STAGES
    buyer = {x["stage"] for x in info["legs"] if x["payer"] == "buyer"}
    assert buyer == set(BUYER_STAGES[term])
    assert all(x["in_landed_cost"] == (x["payer"] == "buyer") for x in info["legs"])
    assert set(info["customs_value_adds"]) == set(CUSTOMS_ADDS[term])


def test_incoterm_endpoint(client):
    b = client.get("/v1/compliance/incoterms").json()
    assert b["total"] == 7 and {i["incoterm"] for i in b["items"]} == set(BUYER_STAGES)
    fob = client.get("/v1/compliance/incoterms", params={"incoterm": "FOB"}).json()["items"][0]
    pay = {x["stage"]: x["payer"] for x in fob["legs"]}
    assert pay["origin_inland"] == "seller" and pay["main_leg"] == "buyer" and pay["duties"] == "buyer"
    assert client.get("/v1/compliance/incoterms", params={"incoterm": "XXX"}).status_code == 422


def test_quote_lines_match_incoterm_payers(client):
    for inc in ("EXW", "FOB", "CIF"):
        q = client.post("/v1/quotes/landed-cost", json=req(inc=inc, modes=["sea_fcl_40"])).json()
        stages = {ln["stage"] for ln in q["options"][0]["lines"]} & set(comp.STAGES)
        assert stages <= set(BUYER_STAGES[inc]), (inc, stages)


# ------------------------------------------------------------------ checklist behaviour
def test_iraq_electronics_sea(client):
    b = post(client, hs_code="8517.13", mode="sea_fcl_40")
    assert b["profile_id"] == "IQ" and b["covered"] and b["product"]["group"] == "electrical"
    d = ids(b)
    assert {"commercial_invoice", "packing_list", "bill_of_lading", "certificate_of_origin", "coc_cosqc",
            "customs_declaration"} <= d
    assert "air_waybill" not in d
    coc = next(x for x in b["documents"] if x["id"] == "coc_cosqc")
    assert coc["requirement"] == "required" and coc["program"] and coc["lead_days"]["max"] >= coc["lead_days"]["min"]
    assert "COSQC" in coc["name_ar"] or "COSQC" in coc["note_ar"]
    assert "telecom_type_approval" in ids(b, "restrictions")
    ind = b["indicative"]
    assert ind["indicative"] and ind["as_of"] == "2026-10" and ind["confidence"] == "low" and ind["source"]
    assert "licensed customs broker" in ind["label_en"] + ind["disclaimer_en"]


def test_transport_document_follows_mode(client):
    assert "air_waybill" in ids(post(client, mode="air", category="electronics"))
    assert "cmr_waybill" in ids(post(client, mode="road", category="electronics"))
    assert "rail_waybill" in ids(post(client, mode="rail", category="electronics"))


def test_hs_code_wins_over_category(client):
    b = post(client, hs_code="0207", category="electronics")
    assert b["product"]["group"] == "food_animal" and b["product"]["resolved_from"] == "hs_code"
    assert {"health_certificate", "halal_certificate", "moh_agri_approval"} <= ids(b)


def test_unknown_product_lowers_confidence_and_says_so(client):
    b = post(client, destination_country="SA")
    assert b["product"]["resolved_from"] == "default" and b["assumptions"]
    assert b["indicative"]["confidence"] == "low"
    b2 = post(client, destination_country="SA", category="electronics")
    assert b2["indicative"]["confidence"] in ("medium", "low")


def test_saudi_saber_and_gulf(client):
    b = post(client, destination_country="SA", category="electronics")
    assert {"saber_pcoc", "saber_scoc"} <= ids(b)
    ae = post(client, destination_country="AE", category="electronics")
    assert "ecas_conformity" in ids(ae)
    for c in ("KW", "QA", "OM", "BH"):
        assert "gcc_conformity" in ids(post(client, destination_country=c, category="toys")), c


def test_egypt_aci_sea_and_air_only(client):
    assert "aci_acid" in ids(post(client, destination_country="EG", category="machinery", mode="sea_lcl"))
    assert "aci_acid" in ids(post(client, destination_country="EG", category="machinery", mode="air"))
    assert "aci_acid" not in ids(post(client, destination_country="EG", category="machinery", mode="road"))


def test_turkey_tareks(client):
    b = post(client, destination_country="TR", category="electronics")
    assert {"tareks_control", "ce_declaration"} <= ids(b)
    assert "surveillance_extra_duties" in ids(b, "restrictions")  # CN origin
    assert "surveillance_extra_duties" not in ids(post(client, destination_country="TR", category="electronics", origin_country="DE"), "restrictions")


def test_eu_member_resolves_and_flags(client):
    b = post(client, destination_country="DE", category="electronics")
    assert b["profile_id"] == "EU" and b["destination_country"] == "DE"
    assert {"eori_number", "ens_ics2", "ce_doc", "gpsr_operator"} <= ids(b)
    steel = post(client, destination_country="NL", hs_code="7208")
    assert "cbam" in ids(steel)
    food = post(client, destination_country="FR", hs_code="0207")
    assert "ched_traces" in ids(food) and "animal_origin" in ids(food, "restrictions")


def test_us_isf_sea_only_and_agency_docs(client):
    assert "isf_10_2" in ids(post(client, destination_country="US", category="electronics", mode="sea_fcl_20"))
    assert "isf_10_2" not in ids(post(client, destination_country="US", category="electronics", mode="air"))
    b = post(client, destination_country="US", category="electronics")
    assert "fcc_authorization" in ids(b) and "uflpa" in ids(b, "restrictions")
    assert "fda_prior_notice" in ids(post(client, destination_country="US", category="food"))
    assert "cpsc_certificate" in ids(post(client, destination_country="US", category="toys"))
    assert b["incoterm"]["customs_value_basis"] == "FOB"


def test_used_and_dangerous_goods_and_origin_flags(client):
    new = post(client, category="production_line", condition="new")
    used = post(client, category="production_line", condition="used")
    assert "used_equipment" not in ids(new, "restrictions") and "used_equipment" in ids(used, "restrictions")
    assert "pre_shipment_inspection_used" in ids(used) and "pre_shipment_inspection_used" not in ids(new)
    dg = post(client, hs_code="850760", dangerous_goods=True)
    assert {"dangerous_goods_declaration", "un38_3_report", "safety_data_sheet"} <= ids(dg)
    plain = post(client, hs_code="850760")
    assert dg["timeline"]["clearance_days"]["max"] > plain["timeline"]["clearance_days"]["max"]
    il = post(client, origin_country="IL", category="electronics")
    assert "israel_origin" in ids(il, "restrictions")
    assert "israel_origin" not in ids(post(client, category="electronics"), "restrictions")
    sev = [comp.SEV_ORDER[r["severity"]] for r in il["restrictions"]]
    assert sev == sorted(sev)


def test_cif_makes_insurance_required(client):
    cif = post(client, incoterm="CIF", category="electronics")
    exw = post(client, incoterm="EXW", category="electronics")
    pick = lambda b: next(x for x in b["documents"] if x["id"] == "insurance_certificate")["requirement"]  # noqa: E731
    assert pick(cif) == "required" and pick(exw) == "recommended"


def test_incoterm_suggestion(client):
    sea = post(client, incoterm="EXW", category="electronics", mode="sea_fcl_40")["incoterm"]["suggestion"]
    assert sea["recommended"] == "FOB" and "EXW" in sea["avoid"] and "DDP" in sea["avoid"]
    assert any(w["code"] == "exw_export_clearance" for w in sea["warnings"])
    air = post(client, incoterm="FOB", category="electronics", mode="air")["incoterm"]["suggestion"]
    assert air["recommended"] == "FCA" and any(w["code"] == "sea_only_term" for w in air["warnings"])
    ok = post(client, incoterm="FOB", category="electronics")["incoterm"]["suggestion"]
    assert ok["supplied_matches_recommendation"] and not ok["warnings"]
    ddp = post(client, incoterm="DDP", category="electronics")["incoterm"]
    assert any(w["code"] == "ddp_importer" for w in ddp["suggestion"]["warnings"])
    assert all(x["payer"] == "seller" for x in ddp["legs"])


def test_timeline_consistency(client):
    for dest in ("IQ", "SA", "EG", "DE", "US", "ZW"):
        t = post(client, destination_country=dest, category="electronics")["timeline"]
        for k in ("pre_shipment_days", "clearance_days", "total_days"):
            assert 0 <= t[k]["min"] <= t[k]["max"]
        assert t["total_days"]["min"] == t["pre_shipment_days"]["min"] + t["clearance_days"]["min"]
        assert t["total_days"]["max"] == t["pre_shipment_days"]["max"] + t["clearance_days"]["max"]
    assert post(client, mode="air", category="electronics")["timeline"]["clearance_days"]["max"] < \
        post(client, mode="sea_fcl_40", category="electronics")["timeline"]["clearance_days"]["max"]


def test_unknown_destination_is_generic_and_low(client):
    b = post(client, destination_country="ZW", category="electronics")
    assert b["profile_id"] == "ZZ" and b["covered"] is False and b["indicative"]["confidence"] == "low"
    assert {"commercial_invoice", "packing_list", "bill_of_lading"} <= ids(b)


def test_deterministic(client):
    a = post(client, destination_country="EG", hs_code="8450", mode="air", condition="used")
    b = post(client, destination_country="EG", hs_code="8450", mode="air", condition="used")
    assert a == b


def test_validation_errors(client):
    for body in ({}, {"destination_country": "iq"}, {"destination_country": "IQ", "hs_code": "8"},
                 {"destination_country": "IQ", "hs_code": "abc"}, {"destination_country": "IQ", "incoterm": "CPT"},
                 {"destination_country": "IQ", "mode": "boat"}, {"destination_country": "IQ", "condition": "broken"},
                 {"destination_country": "IQ", "origin_country": "china"}):
        r = client.post("/v1/compliance/checklist", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", body
    assert client.get("/v1/compliance/countries/iq").status_code == 422


def test_country_endpoints(client):
    lst = client.get("/v1/compliance/countries").json()
    codes = {i["code"] for i in lst["items"]}
    assert {"IQ", "SA", "AE", "KW", "QA", "OM", "BH", "TR", "JO", "EG", "EU", "US"} <= codes
    assert lst["items"][0]["code"] == "IQ"
    p = client.get("/v1/compliance/countries/IT").json()
    assert p["profile_id"] == "EU" and p["requested_country"] == "IT" and "IT" in p["members"]
    assert p["indicative"]["as_of"] == "2026-10"
    z = client.get("/v1/compliance/countries/ZW").json()
    assert z["profile_id"] == "ZZ" and z["indicative"]["confidence"] == "low"


# ------------------------------------------------------------------ quote integration + contract
def test_quote_has_compliance_hint(client):
    q = client.post("/v1/quotes/landed-cost", json=req(inc="FOB")).json()
    h = q["compliance_hint"]
    assert h["destination_country"] == "IQ" and h["covered"] and h["as_of"] == "2026-10"
    assert h["clearance_days"]["min"] <= h["clearance_days"]["max"] and "licensed customs broker" in h["label_en"]
    assert h["details"] == "POST /v1/compliance/checklist"


def test_responses_match_contract(client):
    jsonschema = pytest.importorskip("jsonschema")
    yaml = pytest.importorskip("yaml")
    referencing = pytest.importorskip("referencing")
    from referencing.jsonschema import DRAFT202012

    root = Path(__file__).resolve().parents[3] / "contracts"
    spec_path = root / "openapi" / "logistics.yaml"

    def retrieve(uri):
        path = Path(uri.removeprefix("file://"))
        text = path.read_text()
        data = yaml.safe_load(text)
        return referencing.Resource.from_contents(data, default_specification=DRAFT202012)

    registry = referencing.Registry(retrieve=retrieve)  # type: ignore[call-arg]

    def check(name, body):
        v = jsonschema.Draft202012Validator({"$ref": f"{spec_path.as_uri()}#/components/schemas/{name}"}, registry=registry)
        errs = [f"{list(e.absolute_path)}: {e.message[:150]}" for e in v.iter_errors(body)]
        assert not errs, (name, errs[:5])

    for dest, kw in (("IQ", {"hs_code": "851713"}), ("DE", {"category": "steel"}), ("ZW", {}), ("US", {"category": "food", "mode": "air"})):
        check("ComplianceChecklist", post(client, destination_country=dest, **kw))
    check("ComplianceCountryList", client.get("/v1/compliance/countries").json())
    for c in ("IQ", "FR", "ZW"):
        check("ComplianceProfile", client.get(f"/v1/compliance/countries/{c}").json())
    check("IncotermList", client.get("/v1/compliance/incoterms").json())
    check("LandedCostQuoteResponse", client.post("/v1/quotes/landed-cost", json=req()).json())
