"""Verification-document evidence -> score factors and the 'verified business' badge level (pure, no I/O).

Only documents a reviewer APPROVED reach this module. Each valid document contributes a type weight times a decay
factor: 1.0 until `decay_days` before its expiry, linearly down to `floor` at expiry, 0 once expired. Documents with
no expiry are treated as valid for `default_validity_days` after approval. Two bounded factors come out
(`document_verification` identity/legal papers, `facility_evidence` photos/certificates); each is in [0, 1] so the
points are never negative and never above the factor weight.
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

DocType = Literal[
    "business_license", "company_registry_reference", "bank_reference", "export_license",
    "factory_photos", "iso_certificate", "other_certificate",
]  # fmt: skip
DOC_TYPES: tuple[str, ...] = (
    "business_license", "company_registry_reference", "bank_reference", "export_license",
    "factory_photos", "iso_certificate", "other_certificate",
)  # fmt: skip
Level = Literal["none", "basic", "documented", "audited"]

IDENTITY = {"business_license": 0.5, "company_registry_reference": 0.4, "bank_reference": 0.3, "export_license": 0.3}
FACILITY = {"factory_photos": 0.4, "iso_certificate": 0.5, "other_certificate": 0.25}
CORE = ("business_license", "company_registry_reference")
TRADE = ("bank_reference", "export_license")
SITE = ("factory_photos", "iso_certificate", "other_certificate")
NUMBERED = tuple(t for t in DOC_TYPES if t != "factory_photos")  # types that carry a document number
LEVEL_LABELS = {
    "none": ("No document verification", "لا يوجد توثيق بالمستندات"),
    "basic": ("Basic verified business", "نشاط تجاري موثق (أساسي)"),
    "documented": ("Documented verified business", "نشاط تجاري موثق بالمستندات"),
    "audited": ("Audited verified business", "نشاط تجاري موثق ومدقق"),
}


class VerifiedDoc(BaseModel):
    """An approved document as the scorer sees it: no number, no files, just type and validity dates."""

    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    approved_on: date
    expires_on: date | None = None


class VerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[VerifiedDoc] = []


def effective_expiry(d: VerifiedDoc, default_validity_days: int) -> date:
    return d.expires_on or (d.approved_on + timedelta(days=default_validity_days))


def decay(d: VerifiedDoc, today: date, decay_days: int, floor: float, default_validity_days: int) -> float:
    """1.0 -> `floor` over the last `decay_days` before expiry; 0.0 once expired."""
    exp = effective_expiry(d, default_validity_days)
    if exp < today:
        return 0.0
    left = (exp - today).days
    if left >= decay_days:
        return 1.0
    return floor + (1.0 - floor) * (left / max(1, decay_days))


def valid_docs(ev: VerificationEvidence, today: date, default_validity_days: int) -> list[VerifiedDoc]:
    return [d for d in ev.documents if effective_expiry(d, default_validity_days) >= today]


def _best_per_type(ev: VerificationEvidence, today: date, cfg) -> dict[str, float]:
    best: dict[str, float] = {}
    for d in ev.documents:
        k = decay(d, today, cfg.doc_decay_days, cfg.doc_decay_floor, cfg.doc_default_validity_days)
        if k > 0:
            best[d.doc_type] = max(best.get(d.doc_type, 0.0), k)
    return best


def factor_values(ev: VerificationEvidence | None, today: date, cfg) -> dict[str, float]:
    """{'document_verification': f, 'facility_evidence': f} with f in (0, 1]; absent when nothing valid."""
    if ev is None:
        return {}
    best = _best_per_type(ev, today, cfg)
    out: dict[str, float] = {}
    ident = sum(w * best[t] for t, w in IDENTITY.items() if t in best)
    fac = sum(w * best[t] for t, w in FACILITY.items() if t in best)
    if ident > 0:
        out["document_verification"] = min(1.0, ident)
    if fac > 0:
        out["facility_evidence"] = min(1.0, fac)
    return out


def level_for(ev: VerificationEvidence | None, today: date, cfg, third_party_audit: bool | None, hard_fail: bool = False) -> Level:
    """none/basic/documented/audited. Sanctioned/blocked suppliers never carry a badge."""
    if ev is None or hard_fail:
        return "none"
    have = {d.doc_type for d in valid_docs(ev, today, cfg.doc_default_validity_days)}
    if not have & set(CORE):
        return "none"
    if have & set(TRADE) and have & set(SITE):
        return "audited" if third_party_audit else "documented"
    return "basic"


def value_text(ev: VerificationEvidence, key: str, today: date, cfg) -> str:
    table = IDENTITY if key == "document_verification" else FACILITY
    best = _best_per_type(ev, today, cfg)
    parts = [f"{t}{'' if best[t] >= 1 else ' (expiring, reduced weight)'}" for t in table if t in best]
    return ", ".join(parts) or "none valid"


def expiry_notes(ev: VerificationEvidence, today: date, cfg) -> tuple[list[str], list[str]]:
    """(expired types, types whose decay has started) among approved documents."""
    expired, fading = set(), set()
    for d in ev.documents:
        k = decay(d, today, cfg.doc_decay_days, cfg.doc_decay_floor, cfg.doc_default_validity_days)
        if k == 0.0:
            expired.add(d.doc_type)
        elif k < 1.0:
            fading.add(d.doc_type)
    still = {d.doc_type for d in valid_docs(ev, today, cfg.doc_default_validity_days)}
    return sorted(expired - still), sorted(fading)
