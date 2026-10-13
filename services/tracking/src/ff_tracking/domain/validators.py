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


def validate_container(raw: str) -> Validation:
    ref = re.sub(r"[\s\-]", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{7}", ref):
        return Validation(False, ref, "format: expected 3 owner letters, category U/J/Z and 7 digits")
    if container_check_digit(ref[:10]) != int(ref[10]):
        return Validation(False, ref, "check_digit", ref[:4])
    return Validation(True, ref, None, ref[:4])


def awb_check_digit(serial: str) -> int:
    return int(serial) % 7


def validate_awb(raw: str) -> Validation:
    digits = re.sub(r"[\s\-]", "", raw)
    if not re.fullmatch(r"[0-9]{11}", digits):
        return Validation(False, digits, "format: expected 11 digits (3 airline prefix + 8 serial)")
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


def validate_bl(raw: str) -> Validation:
    ref = re.sub(r"[\s\-/]", "", raw).upper()
    if not re.fullmatch(r"[A-Z0-9]{8,20}", ref):
        return Validation(False, ref, "format: expected 8-20 letters/digits")
    if not re.match(r"[A-Z]{4}", ref):
        return Validation(False, ref, "format: expected a 4-letter carrier (SCAC) prefix")
    return Validation(True, ref, None, ref[:4])


def validate_reference(reference_type: ReferenceType, raw: str) -> Validation:
    return {
        ReferenceType.CONTAINER: validate_container,
        ReferenceType.AWB: validate_awb,
        ReferenceType.VESSEL_IMO: validate_imo,
        ReferenceType.BL: validate_bl,
    }[reference_type](raw)
