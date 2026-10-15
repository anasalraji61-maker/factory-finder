"""Reference validators: ISO 6346 container, air waybill (mod-7), IMO number, basic B/L."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.models import VesselRef


@dataclass(frozen=True, slots=True)
class Validation:
    valid: bool
    normalized: str
    reason: str | None = None
    prefix: str | None = None  # container owner code / B/L prefix / AWB airline prefix
    suggestions: tuple[str, ...] = ()  # fully valid alternatives for common typos (O/0, I/1, ...)
    warnings: tuple[str, ...] = ()  # accepted but suspicious, e.g. ``unusual_format:maersk`` (B/L)


def _letter_values() -> dict[str, int]:
    values: dict[str, int] = {}
    n = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if n % 11 == 0:
            n += 1
        values[ch] = n
        n += 1
    return values


_LETTERS = _letter_values()


def container_check_digit(first_ten: str) -> int:
    """ISO 6346 check digit for the first 10 characters (4 letters + 6 digits)."""
    total = 0
    for i, ch in enumerate(first_ten):
        value = _LETTERS[ch] if ch.isalpha() else int(ch)
        total += value * (2**i)
    return total % 11 % 10


# Characters people confuse when typing/reading identifiers: letter-looking digits and digit-looking letters.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"}
_MAX_SUGGESTIONS = 3


def _container_ok(ref: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{7}", ref)) and container_check_digit(ref[:10]) == int(ref[10])


def container_suggestions(ref: str) -> tuple[str, ...]:
    """Valid ISO 6346 numbers one confusable-character fix away from ``ref`` (O->0, I->1, 0->O, ...).

    Letters in the digit positions (4-10) are read as digits, digits in the owner positions (0-3) as letters;
    the full-normalisation and every single substitution are tried and only check-digit-valid results are kept."""
    if len(ref) != 11 or not re.fullmatch(r"[A-Z0-9]{11}", ref):
        return ()
    found: list[str] = []

    def keep(candidate: str) -> None:
        if candidate != ref and candidate not in found and _container_ok(candidate):
            found.append(candidate)

    keep("".join(_TO_LETTER.get(ch, ch) if i < 4 else _TO_DIGIT.get(ch, ch) for i, ch in enumerate(ref)))
    for i, ch in enumerate(ref):
        sub = _TO_LETTER.get(ch) if i < 4 else _TO_DIGIT.get(ch)
        if sub:
            keep(ref[:i] + sub + ref[i + 1:])
    return tuple(found[:_MAX_SUGGESTIONS])


def validate_container(raw: str) -> Validation:
    ref = re.sub(r"[\s\-]", "", raw).upper()
    if _container_ok(ref):
        return Validation(True, ref, None, ref[:4])
    hints = container_suggestions(ref)
    if not re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{7}", ref):
        return Validation(False, ref, "format: expected 3 owner letters, category U/J/Z and 7 digits", None, hints)
    return Validation(False, ref, "check_digit", ref[:4], hints)


def awb_check_digit(serial: str) -> int:
    return int(serial) % 7


def validate_awb(raw: str) -> Validation:
    digits = re.sub(r"[\s\-./]", "", raw).upper()
    if not re.fullmatch(r"[0-9]{11}", digits):
        fixed = "".join(_TO_DIGIT.get(ch, ch) for ch in digits) if len(digits) == 11 and re.fullmatch(r"[A-Z0-9]+", digits) else ""
        hint = (f"{fixed[:3]}-{fixed[3:]}",) if fixed.isdigit() and awb_check_digit(fixed[3:10]) == int(fixed[10]) else ()
        return Validation(False, digits, "format: expected 11 digits (3 airline prefix + 8 serial)", None, hint)
    prefix, serial = digits[:3], digits[3:]
    normalized = f"{prefix}-{serial}"
    if awb_check_digit(serial[:7]) != int(serial[7]):
        return Validation(False, normalized, "check_digit", prefix)
    return Validation(True, normalized, None, prefix)


def imo_check_ok(seven: str) -> bool:
    total = sum(int(d) * w for d, w in zip(seven[:6], range(7, 1, -1), strict=True))
    return total % 10 == int(seven[6])


def validate_imo(raw: str) -> Validation:
    ref = re.sub(r"^IMO[:#.]*", "", re.sub(r"[\s\-]", "", raw).upper())
    if not re.fullmatch(r"[0-9]{7}", ref):
        return Validation(False, ref, "format: expected 7 digits")
    if ref[0] == "0":
        return Validation(False, ref, "format: an IMO number never starts with 0")
    if not imo_check_ok(ref):
        return Validation(False, ref, "check_digit")
    return Validation(True, ref)


_VESSEL_TITLE = re.compile(r"^(?:M\s*/\s*[VTS]|M\.[VTS]\.?|MV|MT|SS|MS)(?=[\s.:/-]+\S)[\s.:/-]*", re.IGNORECASE)
_NAME_IMO = re.compile(r"\(?\s*IMO[\s:#.-]*([0-9]{7})\s*\)?", re.IGNORECASE)


def clean_vessel_name(raw: str | None) -> str | None:
    """Upper-case, control characters and ``M/V`` / ``MV`` / ``MT`` titles removed, whitespace collapsed."""
    text = strip_control(raw)
    if not text:
        return None
    text = _NAME_IMO.sub(" ", text)
    if re.fullmatch(r"M\s*/\s*[VTS]|M\.[VTS]\.?|MV|MT", text.strip(), re.IGNORECASE):
        return None
    return " ".join(_VESSEL_TITLE.sub("", " ".join(text.split())).upper().split()) or None


def parse_vessel(value: object) -> VesselRef | None:
    """Provider vessel object (``name``, ``imo``, ``voyage``) -> ``VesselRef``.

    * the IMO may sit in ``imo`` (``"IMO 9074729"``, ``9074729``) or inside the name (``"MSC GULSUN (IMO 9811000)"``)
    * an IMO is kept only when it passes the check digit; a bad one is dropped, the name is kept
    * no usable name -> ``None``
    """
    if not isinstance(value, Mapping):
        return None
    name_raw = str(value.get("name") or "")
    imo_raw = str(value.get("imo") or "")
    if not imo_raw and (m := _NAME_IMO.search(name_raw)):
        imo_raw = m.group(1)
    imo = None
    if imo_raw:
        v = validate_imo(imo_raw)
        imo = v.normalized if v.valid else None
    name = clean_vessel_name(name_raw)
    if not name:
        return None
    voyage = strip_control(str(value["voyage"])) if value.get("voyage") not in (None, "") else None
    return VesselRef(name=name[:120], imo=imo, voyage=(voyage or "").upper()[:20] or None)


_BL_NOISE = re.compile(
    r"^(?:B\s*/\s*L|(?:BILL\s+OF\s+LADING|HBL|MBL|BOL|BL)(?![A-Z0-9]))\s*(?:NO\.?(?![A-Z])|NUMBER|#)?\s*[:#.]?\s*",
    re.IGNORECASE)

# Best-effort B/L number shapes per carrier SCAC prefix (UNVERIFIED, indicative): a mismatch only adds a warning.
_BL_FORMATS: dict[str, tuple[str, re.Pattern[str]]] = {
    **{p: ("maersk", re.compile(r"(?:MAEU|SUDU)?[0-9]{9}")) for p in ("MAEU", "SUDU")},
    **{p: ("msc", re.compile(r"(?:MEDU|MSCU)[A-Z0-9]{8}")) for p in ("MEDU", "MSCU")},
    "COSU": ("cosco", re.compile(r"COSU[0-9]{10}")),
    "OOLU": ("oocl", re.compile(r"OOLU[0-9]{10}")),
    "EGLV": ("evergreen", re.compile(r"EGLV[0-9]{12}")),
    "HLCU": ("hapag_lloyd", re.compile(r"HLCU[A-Z0-9]{8,14}")),
    "CMDU": ("cma_cgm", re.compile(r"CMDU[A-Z0-9]{7,12}")),
    "ONEY": ("one", re.compile(r"ONEY[A-Z0-9]{8,12}")),
    "YMLU": ("yang_ming", re.compile(r"YMLU[A-Z0-9]{9,10}")),
    "ZIMU": ("zim", re.compile(r"ZIMU[A-Z0-9]{8,12}")),
    "HDMU": ("hmm", re.compile(r"HDMU[A-Z0-9]{8,12}")),
}


def validate_bl(raw: str) -> Validation:
    """Tolerant B/L check: strips "B/L No.:" labels, spaces and separators. A 4-letter SCAC-style prefix gives the
    carrier hint (and a ``unusual_format:<carrier>`` warning when the rest does not look like that carrier's
    numbers); pure-digit numbers (Maersk and others issue them) are accepted without a prefix."""
    ref = re.sub(r"[\s\-/._#:]", "", _BL_NOISE.sub("", raw.strip())).upper()
    if not re.fullmatch(r"[A-Z0-9]{8,20}", ref):
        return Validation(False, ref, "format: expected 8-20 letters/digits")
    if re.match(r"[A-Z]{4}", ref):
        fmt = _BL_FORMATS.get(ref[:4])
        warn = (f"unusual_format:{fmt[0]}",) if fmt and not fmt[1].fullmatch(ref) else ()
        return Validation(True, ref, None, ref[:4], warnings=warn)
    if ref.isdigit() and len(ref) >= 9:
        return Validation(True, ref)
    return Validation(False, ref, "format: expected a 4-letter carrier (SCAC) prefix")


def validate_reference(reference_type: ReferenceType, raw: str) -> Validation:
    return {
        ReferenceType.CONTAINER: validate_container,
        ReferenceType.AWB: validate_awb,
        ReferenceType.VESSEL_IMO: validate_imo,
        ReferenceType.BL: validate_bl,
    }[reference_type](raw)


def strip_control(value: str | None) -> str | None:
    """Free text hygiene: drop control / bidi / zero-width / private-use characters, collapse whitespace.
    Empty results become ``None``."""
    import unicodedata

    if value is None:
        return None
    kept = "".join(" " if ch.isspace() else ch for ch in value
                   if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn"))
    return " ".join(kept.split()) or None
