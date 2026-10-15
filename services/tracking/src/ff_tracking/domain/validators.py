"""Reference validators: ISO 6346 container, air waybill (mod-7), IMO number, basic B/L."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ff_tracking.domain.enums import ReferenceType


@dataclass(frozen=True, slots=True)
class Validation:
    valid: bool
    normalized: str
    reason: str | None = None
    prefix: str | None = None  # container owner code / B/L prefix / AWB airline prefix
    suggestions: tuple[str, ...] = ()  # fully valid alternatives for common typos (O/0, I/1, ...)


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
    ref = re.sub(r"^IMO", "", re.sub(r"[\s\-]", "", raw).upper())
    if not re.fullmatch(r"[0-9]{7}", ref):
        return Validation(False, ref, "format: expected 7 digits")
    if not imo_check_ok(ref):
        return Validation(False, ref, "check_digit")
    return Validation(True, ref)


_BL_NOISE = re.compile(r"^(?:B/?L|BILL\s+OF\s+LADING|HBL|MBL|BOL)\s*(?:NO\.?|NUMBER|#)?\s*[:#.]?\s*", re.IGNORECASE)


def validate_bl(raw: str) -> Validation:
    """Tolerant B/L check: strips "B/L No.:" labels, spaces and separators. A 4-letter SCAC-style prefix gives the
    carrier hint; pure-digit numbers (some carriers issue them) are accepted without a prefix."""
    ref = re.sub(r"[\s\-/._#:]", "", _BL_NOISE.sub("", raw.strip())).upper()
    if not re.fullmatch(r"[A-Z0-9]{8,20}", ref):
        return Validation(False, ref, "format: expected 8-20 letters/digits")
    if re.match(r"[A-Z]{4}", ref):
        return Validation(True, ref, None, ref[:4])
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
