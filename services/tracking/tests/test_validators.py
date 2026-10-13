import pytest

from ff_tracking.domain.carriers import carrier_for_container_owner
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.validators import (
    container_check_digit,
    validate_awb,
    validate_bl,
    validate_container,
    validate_imo,
    validate_reference,
)


def test_container_valid_and_normalised():
    v = validate_container("csqu 305438-3")
    assert v.valid and v.normalized == "CSQU3054383" and v.prefix == "CSQU"


@pytest.mark.parametrize("ref", ["CSQU3054384", "CSQU305438", "CSQA3054383", "1234567890A", ""])
def test_container_invalid(ref):
    assert not validate_container(ref).valid


def test_container_check_digit_skips_multiples_of_11():
    assert validate_container("MSCU" + "639870" + str(container_check_digit("MSCU639870"))).valid


def test_awb():
    v = validate_awb("176-12345675")
    assert v.valid and v.normalized == "176-12345675" and v.prefix == "176"
    assert validate_awb("17612345675").valid
    assert validate_awb("176-12345676").reason == "check_digit"
    assert not validate_awb("176-1234").valid


def test_imo():
    assert validate_imo("IMO 9074729").valid
    assert validate_imo("9074729").normalized == "9074729"
    assert validate_imo("9074728").reason == "check_digit"
    assert not validate_imo("12345").valid


def test_bl_basic():
    assert validate_bl("MAEU 123456789").valid
    assert not validate_bl("12345678").valid
    assert not validate_bl("AB1").valid


def test_dispatch_and_carrier_detection():
    assert validate_reference(ReferenceType.AWB, "176-12345675").valid
    assert carrier_for_container_owner("MSCU").code == "msc"
