"""Guess what kind of reference a user typed (container / AWB / IMO / B/L) without being told.

Several shapes overlap (an 11-digit AWB is also a plausible all-digit B/L; a check-digit-valid container is also an
8-20 character B/L), so the result is a ranked list of candidates. Confidence is ``high`` only when exactly one
type fits; with several candidates every one is capped at ``medium``. B/L candidates are ``high`` only for a known carrier
prefix whose number matches that carrier's shape (otherwise it may be a mistyped container/AWB)."""

from __future__ import annotations

from dataclasses import dataclass

from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.validators import _BL_FORMATS, validate_reference

_ORDER = (ReferenceType.CONTAINER, ReferenceType.AWB, ReferenceType.VESSEL_IMO, ReferenceType.BL)


@dataclass(frozen=True, slots=True)
class Candidate:
    reference_type: ReferenceType
    normalized: str
    confidence: str  # high | medium
    prefix: str | None = None


def detect_reference(raw: str) -> list[Candidate]:
    hits = []
    for rt in _ORDER:
        v = validate_reference(rt, raw)
        if v.valid:
            hits.append((rt, v))
    many = len(hits) > 1
    out = []
    for rt, v in hits:
        medium = many or (rt is ReferenceType.BL and (bool(v.warnings) or v.prefix not in _BL_FORMATS))
        out.append(Candidate(rt, v.normalized, "medium" if medium else "high", v.prefix))
    return out
