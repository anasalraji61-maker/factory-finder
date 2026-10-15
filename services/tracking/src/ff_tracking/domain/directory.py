"""Bundled, offline carrier directory (data/carrier_directory.json) used to suggest a carrier from a reference.

INDICATIVE only (``as_of`` in the file): ocean SCAC / BIC owner prefixes and 3-digit AWB airline prefixes change and
some are shared; entries with ``confidence: low`` are best effort. A suggestion never overrides a carrier the user chose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ff_tracking.domain.enums import ReferenceType

_FILE = Path(__file__).resolve().parent.parent / "data" / "carrier_directory.json"


@dataclass(frozen=True, slots=True)
class CarrierSuggestion:
    code: str
    name: str
    name_ar: str | None
    scac: str | None
    iata_code: str | None
    awb_prefix: str | None
    basis: str  # container_owner_prefix | bl_scac_prefix | awb_prefix
    confidence: str  # high | medium | low
    as_of: str
    indicative: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "name": self.name, "name_ar": self.name_ar, "scac": self.scac,
            "iata_code": self.iata_code, "awb_prefix": self.awb_prefix, "basis": self.basis,
            "confidence": self.confidence, "as_of": self.as_of, "indicative": self.indicative,
        }


@dataclass(frozen=True, slots=True)
class Directory:
    as_of: str
    ocean: tuple[dict[str, Any], ...]
    airlines: tuple[dict[str, Any], ...]
    lessor_prefixes: frozenset[str]


@lru_cache(maxsize=1)
def load_directory(path: Path | None = None) -> Directory:
    raw = json.loads((path or _FILE).read_text(encoding="utf-8"))
    return Directory(raw["as_of"], tuple(raw["ocean"]), tuple(raw["airlines"]), frozenset(raw.get("lessor_prefixes", ())))


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    d = load_directory()
    container: dict[str, dict] = {}
    bl: dict[str, dict] = {}
    awb: dict[str, dict] = {}
    for c in d.ocean:
        for p in c.get("container_prefixes", ()):
            container.setdefault(p, c)
        for p in (*c.get("bl_prefixes", ()), c.get("scac") or ""):
            if p:
                bl.setdefault(p, c)
    for a in d.airlines:
        if a.get("awb_prefix"):
            awb.setdefault(a["awb_prefix"], a)
    return container, bl, awb


def suggest_carrier(reference_type: ReferenceType, prefix: str | None) -> CarrierSuggestion | None:
    """Carrier suggestion from the already validated reference prefix (container owner code, B/L SCAC, AWB prefix).
    Leasing-company container prefixes return ``None`` (the box may sail with any carrier)."""
    if not prefix or reference_type is ReferenceType.VESSEL_IMO:
        return None
    d = load_directory()
    container, bl, awb = _indexes()
    key = prefix.upper()
    if reference_type is ReferenceType.CONTAINER:
        entry, basis = (None, "") if key in d.lessor_prefixes else (container.get(key), "container_owner_prefix")
    elif reference_type is ReferenceType.BL:
        entry, basis = bl.get(key), "bl_scac_prefix"
    else:
        entry, basis = awb.get(prefix), "awb_prefix"
    if entry is None:
        return None
    # The bundled list is compiled offline and never verified against the BIC registry / IATA: never claim "high".
    conf = entry.get("confidence", "medium")
    conf = conf if conf in ("medium", "low") else "medium"
    return CarrierSuggestion(
        code=entry["code"], name=entry["name"], name_ar=entry.get("name_ar"), scac=entry.get("scac"),
        iata_code=entry.get("iata_code"), awb_prefix=entry.get("awb_prefix"), basis=basis,
        confidence=conf, as_of=d.as_of)
