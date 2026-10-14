"""Import-compliance advisor: documents checklist, restriction flags, incoterm split, clearance timeline.

Pure and deterministic: everything comes from data/compliance.json. All output is INDICATIVE.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .duties import load_json
from .incoterms import BUYER_STAGES, CUSTOMS_ADDS

FAMILY = {"sea_lcl": "sea", "sea_fcl_20": "sea", "sea_fcl_40": "sea", "sea_fcl_40hc": "sea", "air": "air",
          "rail": "rail", "road": "road"}
CONF_RANK = {"low": 0, "medium": 1, "high": 2}
CONF_NAME = {v: k for k, v in CONF_RANK.items()}
STAGE_ORDER = {"pre_shipment": 0, "shipping": 1, "clearance": 2}
REQ_ORDER = {"required": 0, "conditional": 1, "recommended": 2}
SEV_ORDER = {"prohibited": 0, "licence_required": 1, "restricted": 2, "enhanced_scrutiny": 3}
STAGES = ["origin_inland", "origin_handling", "main_leg", "insurance", "destination_handling", "duties", "taxes",
          "clearance", "destination_inland"]


@lru_cache(maxsize=1)
def data() -> dict:
    return load_json("compliance.json")


@lru_cache(maxsize=1)
def _chapter_group() -> dict[str, str]:
    return {ch: g for g, v in data()["groups"].items() for ch in v["chapters"]}


@lru_cache(maxsize=1)
def _member_profile() -> dict[str, str]:
    m = {}
    for pid, p in data()["countries"].items():
        m[pid] = pid
        for c in p.get("members", []):
            m[c] = pid
    return m


def profile_for(country: str) -> tuple[dict, str]:
    """(profile, profile_id); unknown destinations get the generic default profile (covered=false)."""
    pid = _member_profile().get(country)
    if pid is None:
        return data()["default_country"], "ZZ"
    return data()["countries"][pid], pid


def profile_ids() -> list[str]:
    return sorted(data()["countries"], key=lambda k: (data()["countries"][k]["priority"], k))


def digits_of(hs_code: str | None) -> str:
    return re.sub(r"\D", "", hs_code or "")


def resolve_product(hs_code: str | None, category: str | None) -> dict:
    d = data()
    digits = digits_of(hs_code)
    group, via, chapter = "general_goods", "default", None
    if len(digits) >= 2:
        chapter = digits[:2]
        group, via = _chapter_group().get(chapter, "general_goods"), "hs_code"
    elif category:
        key = re.sub(r"[\s-]+", "_", category.strip().lower())
        g = d["category_aliases"].get(key) or (key if key in d["groups"] else None)
        if g:
            group, via = g, "category"
    return {"hs_code": digits or None, "chapter": chapter, "group": group, "resolved_from": via,
            "group_name_en": d["groups"][group]["name_en"], "group_name_ar": d["groups"][group]["name_ar"]}


def _applies(item: dict, prod: dict, family: str, origin: str | None, condition: str) -> bool:
    groups = item.get("groups", "*")
    if groups != "*" and prod["group"] not in groups:
        return False
    if "hs_prefixes" in item and not any(prod["hs_code"] and prod["hs_code"].startswith(p) for p in item["hs_prefixes"]):
        return False
    if "condition" in item and item["condition"] != condition:
        return False
    if "modes" in item and family not in item["modes"]:
        return False
    return not ("origins" in item and (origin or "") not in item["origins"])


def _doc_out(did: str, spec: dict, profile_conf: str) -> dict:
    lib = data()["documents"].get(did, {})
    lead = spec.get("lead_days")
    return {"id": did, "requirement": spec["requirement"], "stage": spec.get("stage") or lib.get("stage", "shipping"),
            "name_en": spec.get("name_en") or lib.get("name_en", ""), "name_ar": spec.get("name_ar") or lib.get("name_ar", ""),
            "note_en": spec.get("note_en") or lib.get("note_en", ""), "note_ar": spec.get("note_ar") or lib.get("note_ar", ""),
            "program": bool(spec.get("program", False)), "lead_days": dict(lead) if lead else None,
            "confidence": spec.get("confidence", profile_conf)}


def build_documents(profile: dict, prod: dict, family: str, origin: str | None, incoterm: str, condition: str,
                    dangerous: bool) -> list[dict]:
    d = data()
    specs: dict[str, dict] = {}

    def put(did: str, spec: dict):
        specs[did] = {**specs.get(did, {}), **{k: v for k, v in spec.items() if k not in ("groups", "hs_prefixes", "modes", "origins", "condition")}}

    for s in d["base_documents"]:
        put(s["id"], s)
    put(d["transport_documents"][family], {"requirement": "required"})
    if incoterm == "CIF":
        put("insurance_certificate", {"requirement": "required"})
    for s in d["group_documents"]:
        if _applies(s, prod, family, origin, condition):
            put(s["id"], s)
    if dangerous:
        for s in d["dangerous_goods_documents"]:
            put(s["id"], s)
    for s in profile["documents"]:
        if _applies(s, prod, family, origin, condition):
            put(s["id"], s)
    docs = [_doc_out(i, s, profile["confidence"]) for i, s in specs.items()]
    docs.sort(key=lambda x: (STAGE_ORDER[x["stage"]], REQ_ORDER[x["requirement"]]))
    return docs


def build_restrictions(profile: dict, prod: dict, origin: str | None, condition: str) -> list[dict]:
    out = []
    for r in profile["restrictions"]:
        has_prod = "groups" in r or "hs_prefixes" in r
        has_origin, has_cond = "origins" in r, "condition" in r
        if not (has_prod or has_origin or has_cond):
            scope = "general"
        else:
            if has_prod:
                hs_hit = any(prod["hs_code"] and prod["hs_code"].startswith(p) for p in r.get("hs_prefixes", []))
                if not (prod["group"] in r.get("groups", []) or hs_hit):
                    continue
            if has_origin and (origin or "") not in r["origins"]:
                continue
            if has_cond and r["condition"] != condition:
                continue
            scope = "product" if has_prod else ("origin" if has_origin else "condition")
        out.append({"id": r["id"], "severity": r["severity"], "scope": scope, "text_en": r["text_en"],
                    "text_ar": r["text_ar"], "confidence": r.get("confidence", profile["confidence"])})
    out.sort(key=lambda x: (SEV_ORDER[x["severity"]], x["id"]))
    return out


def incoterm_legs(incoterm: str) -> list[dict]:
    """Who pays each landed-cost stage; derived from the SAME table the quote engine uses."""
    labels, buyer = data()["stage_labels"], BUYER_STAGES[incoterm]
    return [{"stage": s, "label_en": labels[s]["en"], "label_ar": labels[s]["ar"],
             "payer": "buyer" if s in buyer else "seller", "in_landed_cost": s in buyer} for s in STAGES]


def incoterm_info(incoterm: str) -> dict:
    t = data()["incoterms"][incoterm]
    return {"incoterm": incoterm, "text_en": t["text_en"], "text_ar": t["text_ar"], "sea_only": t["sea_only"],
            "legs": incoterm_legs(incoterm), "customs_value_adds": [s for s in STAGES if s in CUSTOMS_ADDS[incoterm]]}


def _w(code: str, en: str, ar: str) -> dict:
    return {"code": code, "en": en, "ar": ar}


def suggest_incoterm(profile: dict, origin: str | None, family: str, supplied: str, has_programs: bool) -> dict:
    sea = family == "sea"
    rec = "FOB" if sea else "FCA"
    alts = ["CIF", "CFR"] if sea else ["DAP"]
    avoid = ["EXW"] + (["DDP"] if profile["ddp_feasible"] == "rarely" else []) + ([] if sea else ["FOB", "CFR", "CIF"])
    warns = []
    if supplied == "EXW":
        warns.append(_w("exw_export_clearance",
                        "EXW makes the buyer responsible for export clearance in the origin country, which a foreign buyer can rarely do"
                        + (" (especially in China, where export declarations need a local entity)." if origin == "CN" else "."),
                        "بموجب EXW يتحمل المشتري التخليص التصديري في بلد المنشأ وهو ما يصعب على المشتري الأجنبي"
                        + (" (خصوصاً في الصين حيث يحتاج التصدير جهة محلية)." if origin == "CN" else ".")))
    if supplied in ("FOB", "CFR", "CIF") and not sea:
        warns.append(_w("sea_only_term", f"{supplied} is a sea-only term; for air, road or rail use FCA or DAP.",
                        f"{supplied} مصطلح للشحن البحري فقط؛ للشحن الجوي أو البري أو بالقطار استخدم FCA أو DAP."))
    if supplied == "DDP":
        warns.append(_w("ddp_importer", "DDP requires the seller to act as importer of record in the destination"
                        + ("; this is rarely workable here and can hide duties, VAT and fees in the price." if profile["ddp_feasible"] == "rarely" else "; check the seller can and will do it."),
                        "يتطلب DDP أن يعمل البائع كمستورد مسجّل في الوجهة"
                        + ("؛ وهو نادراً ما يكون عملياً هنا وقد يخفي الرسوم والضريبة والأجور في السعر." if profile["ddp_feasible"] == "rarely" else "؛ تأكد أن البائع قادر وراغب.")))
    if supplied == "DAP":
        warns.append(_w("dap_clearance", "DAP leaves import duties, taxes and customs clearance with the buyer; keep a local broker ready.",
                        "يترك DAP الرسوم والضرائب والتخليص الجمركي على المشتري؛ جهّز مخلّصاً محلياً."))
    if supplied in ("CFR", "CIF") and sea:
        warns.append(_w("sea_leg_seller_booked", f"Under {supplied} the seller chooses the carrier and routing; compare the freight inside the price with a separate quote.",
                        f"في {supplied} يختار البائع الناقل والمسار؛ قارن الشحن المتضمَّن في السعر بعرض مستقل."))
    prog_en = (" Destination conformity/pre-shipment programs apply, and controlling the booking lets the buyer sequence inspection and certificates before cargo moves." if has_programs else "")
    prog_ar = (" تنطبق برامج مطابقة/فحص قبل الشحن في الوجهة، والتحكم بالحجز يتيح للمشتري ترتيب الفحص والشهادات قبل تحرك البضاعة." if has_programs else "")
    if sea:
        en = (f"FOB: the seller clears export and loads on the vessel; the buyer books sea freight and insurance (more control, usually cheaper freight). "
              f"CIF/CFR is simpler for a first order but the seller picks the carrier.{prog_en}")
        ar = (f"FOB: يخلّص البائع التصدير ويحمّل على السفينة؛ ويحجز المشتري الشحن البحري والتأمين (تحكم أكبر وشحن أرخص غالباً). "
              f"CIF/CFR أبسط للطلب الأول لكن البائع يختار الناقل.{prog_ar}")
    else:
        en = (f"FCA: the seller clears export and hands over to the buyer's carrier at an agreed place (FOB/CFR/CIF are sea-only). "
              f"DAP is an easier alternative when the seller can deliver to the destination.{prog_en}")
        ar = (f"FCA: يخلّص البائع التصدير ويسلّم لناقل المشتري في مكان متفق عليه (FOB/CFR/CIF للبحر فقط). "
              f"DAP بديل أسهل عندما يستطيع البائع التسليم حتى الوجهة.{prog_ar}")
    return {"recommended": rec, "alternatives": alts, "avoid": avoid, "rationale_en": en, "rationale_ar": ar, "warnings": warns,
            "supplied_matches_recommendation": supplied == rec}


def _rng(a: int, b: int) -> dict:
    return {"min": a, "max": b}


def build_timeline(profile: dict, docs: list[dict], family: str, dangerous: bool) -> dict:
    leads = [x["lead_days"] for x in docs if x["lead_days"] and x["requirement"] == "required"]
    pre = _rng(max((x["min"] for x in leads), default=0), sum(x["max"] for x in leads))
    cl = dict(profile["clearance_days"][family])
    if dangerous:
        cl = _rng(cl["min"] + 1, cl["max"] + 3)
    return {"pre_shipment_days": pre, "clearance_days": cl, "total_days": _rng(pre["min"] + cl["min"], pre["max"] + cl["max"]),
            "basis_en": "Pre-shipment: longest single required item (min) to all required items in sequence (max). Clearance: arrival at the destination port/border until release. Transit time is NOT included (see the landed-cost quote).",
            "basis_ar": "قبل الشحن: أطول مستند مطلوب (الأدنى) إلى جميع المستندات المطلوبة بالتسلسل (الأقصى). التخليص: من وصول البضاعة إلى ميناء/منفذ الوجهة حتى الإفراج. لا يشمل زمن العبور (انظر عرض التكلفة الواصلة)."}


def indicative_block(profile: dict, docs: list[dict], prod: dict) -> dict:
    d = data()
    rank = CONF_RANK[profile["confidence"]]
    for x in docs:
        if x["program"] and x["requirement"] == "required":
            rank = min(rank, CONF_RANK[x["confidence"]])
    if not profile.get("covered", True):
        rank = 0
    elif prod["resolved_from"] == "default":
        rank = max(rank - 1, 0)
    return {"indicative": True, "source": profile["source"], "as_of": profile["as_of"], "confidence": CONF_NAME[rank],
            "label_en": d["label_en"], "label_ar": d["label_ar"], "disclaimer_en": d["disclaimer_en"], "disclaimer_ar": d["disclaimer_ar"]}


def checklist(destination: str, hs_code: str | None, category: str | None, origin: str | None, incoterm: str,
              mode: str, condition: str = "new", dangerous_goods: bool = False) -> dict:
    profile, pid = profile_for(destination)
    family = FAMILY[mode]
    prod = resolve_product(hs_code, category)
    prod["condition"] = condition
    docs = build_documents(profile, prod, family, origin, incoterm, condition, dangerous_goods)
    restr = build_restrictions(profile, prod, origin, condition)
    has_programs = any(x["program"] and x["requirement"] == "required" and x["stage"] == "pre_shipment" for x in docs)
    assumptions = []
    if prod["resolved_from"] == "default":
        assumptions.append("No HS code or known category given: generic goods assumed, product-specific documents and flags are not included.")
    if prod["resolved_from"] == "category" and not hs_code:
        assumptions.append("Product group inferred from the category; give an HS code for a more precise result.")
    if not origin:
        assumptions.append("Origin country not given: origin-specific flags (e.g. anti-dumping, forced-labour or boycott rules) are not evaluated.")
    if not profile.get("covered", True):
        assumptions.append(f"No curated data for {destination}: generic baseline returned.")
    if dangerous_goods:
        assumptions.append("Dangerous goods add carrier acceptance and clearance time.")
    inc = incoterm_info(incoterm)
    inc["customs_value_basis"] = profile["customs_value_basis"]
    inc["suggestion"] = suggest_incoterm(profile, origin, family, incoterm, has_programs)
    inc["selected"] = incoterm
    return {"destination_country": destination, "profile_id": pid, "profile_name_en": profile["name_en"],
            "profile_name_ar": profile["name_ar"], "covered": profile.get("covered", True), "origin_country": origin,
            "mode": mode, "product": prod, "documents": docs, "restrictions": restr, "incoterm": inc,
            "timeline": build_timeline(profile, docs, family, dangerous_goods),
            "authority_en": profile["authority_en"], "authority_ar": profile["authority_ar"],
            "notes_en": profile["notes_en"], "notes_ar": profile["notes_ar"],
            "indicative": indicative_block(profile, docs, prod), "assumptions": assumptions}


def hint(destination: str, hs_code: str | None, category: str | None, origin: str | None, incoterm: str, mode: str,
         dangerous_goods: bool = False) -> dict:
    c = checklist(destination, hs_code, category, origin, incoterm, mode, "new", dangerous_goods)
    prog = [x["id"] for x in c["documents"] if x["program"] and x["requirement"] == "required"]
    sev = min((SEV_ORDER[r["severity"]] for r in c["restrictions"] if r["scope"] != "general"), default=None)
    names = {v: k for k, v in SEV_ORDER.items()}
    return {"destination_country": destination, "covered": c["covered"], "product_group": c["product"]["group"],
            "required_programs": prog, "restriction_flags": sum(1 for r in c["restrictions"] if r["scope"] != "general"),
            "highest_severity": names[sev] if sev is not None else None,
            "clearance_days": c["timeline"]["clearance_days"], "pre_shipment_days": c["timeline"]["pre_shipment_days"],
            "confidence": c["indicative"]["confidence"], "as_of": c["indicative"]["as_of"],
            "label_en": data()["label_en"], "label_ar": data()["label_ar"], "details": "POST /v1/compliance/checklist"}


def country_summary(pid: str) -> dict:
    p = data()["default_country"] if pid == "ZZ" else data()["countries"][pid]
    return {"code": pid, "name_en": p["name_en"], "name_ar": p["name_ar"], "covered": p.get("covered", True),
            "members": p.get("members", []), "confidence": p["confidence"], "as_of": p["as_of"],
            "customs_system": p["customs_system"]}
