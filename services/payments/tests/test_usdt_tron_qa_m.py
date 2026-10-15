"""QA round M: TRON address vectors built with hashlib, config-time rejection, explorer robustness (offline)."""

import hashlib
from decimal import Decimal

import httpx
import pytest
from conftest import make_settings

from ff_payments.domain.errors import UpstreamUnavailable
from ff_payments.providers.base import InvoiceSpec, TrackedInvoice
from ff_payments.providers.mock import MockProvider
from ff_payments.providers.registry import build_provider
from ff_payments.providers.usdt_tron import (
    ExplorerClient,
    ProviderNotConfigured,
    UsdtTronProvider,
    is_valid_tron_address,
)

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58check(payload: bytes) -> str:
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return out


def make_addr(seed: str, version: int = 0x41) -> str:
    return b58check(bytes([version]) + hashlib.sha256(seed.encode()).digest()[:20])


GOOD = [a for a in (make_addr(f"s{i}") for i in range(60)) if a.startswith("T") and len(a) == 34][:30]


def test_constructed_vectors_exist():
    assert len(GOOD) >= 20  # 0x41-prefixed 25-byte payloads encode to 'T...' 34 chars


@pytest.mark.parametrize("a", GOOD)
def test_constructed_valid(a):
    assert is_valid_tron_address(a)


def test_constructed_invalid_variants():
    a = GOOD[0]
    assert not is_valid_tron_address(make_addr("x", 0x00))
    assert not is_valid_tron_address(b58check(b"\x41" + b"\x01" * 19))
    assert not is_valid_tron_address(a.lower()) and not is_valid_tron_address(a + " ")
    assert not is_valid_tron_address("0x" + "a" * 40)
    assert not is_valid_tron_address(None) and not is_valid_tron_address(b"T" * 34)
    assert not is_valid_tron_address("T" + "z" * 33)


def test_every_single_char_corruption_is_caught():
    a = GOOD[1]
    for i in range(1, len(a)):
        for c in "1Az":
            if c != a[i]:
                assert not is_valid_tron_address(a[:i] + c + a[i + 1:])


def test_config_rejects_bad_addresses_at_build():
    ok = dict(provider="usdt_tron", usdt_receive_address=GOOD[0], usdt_contract=GOOD[1],
              usdt_explorer_url="https://explorer.invalid")
    assert isinstance(build_provider(make_settings(**ok)), UsdtTronProvider)
    for bad in ({"usdt_receive_address": GOOD[0][:-1] + ("1" if GOOD[0][-1] != "1" else "2")},
                {"usdt_contract": "nope"}, {"usdt_explorer_url": "ftp://x"},
                {"usdt_explorer_url": "http://explorer.invalid"}):
        with pytest.raises(ProviderNotConfigured):
            build_provider(make_settings(**{**ok, **bad}))


def test_unset_config_still_builds():
    assert isinstance(build_provider(make_settings(provider="usdt_tron")), UsdtTronProvider)


def tracked(addr=None):
    return TrackedInvoice("ref", "memo", addr or GOOD[0], Decimal("10.000001"), 0)


def client(handler):
    return ExplorerClient("https://explorer.invalid", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("payload", [[], [1], {"data": 5}, {"data": None}, {"data": "x"}, "str", 7, None])
async def test_odd_json_shapes_are_upstream_unavailable(payload):
    p = UsdtTronProvider(address=GOOD[0], contract=GOOD[1],
                         explorer=client(lambda r: httpx.Response(200, json=payload)))
    with pytest.raises(UpstreamUnavailable):
        await p.poll(tracked())


async def test_non_json_5xx_and_timeout():
    def boom(r):
        raise httpx.ReadTimeout("t")
    for h in (lambda r: httpx.Response(200, content=b"<html>"), lambda r: httpx.Response(503), boom):
        p = UsdtTronProvider(address=GOOD[0], contract=GOOD[1], explorer=client(h))
        with pytest.raises(UpstreamUnavailable):
            await p.poll(tracked())


async def test_429_backs_off_without_hammering():
    calls = []

    def h(r):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "30"})
    p = UsdtTronProvider(address=GOOD[0], contract=GOOD[1], explorer=client(h))
    for _ in range(5):
        with pytest.raises(UpstreamUnavailable):
            await p.poll(tracked())
    assert len(calls) == 1


async def test_timeout_bounded_and_key_not_leaked():
    ex = ExplorerClient("https://explorer.invalid", api_key="SECRETKEY123")
    assert ex._c.timeout.read is not None and ex._c.timeout.read <= 10
    assert "SECRETKEY123" not in repr(make_settings(usdt_explorer_api_key="SECRETKEY123"))
    await ex.aclose()


async def test_invoice_for_other_address_never_matches():
    tx = {"transaction_id": "t", "value": "10000001", "block_number": 5, "block_timestamp": 10,
          "token_info": {"address": GOOD[1]}}
    p = UsdtTronProvider(address=GOOD[0], contract=GOOD[1],
                         explorer=client(lambda r: httpx.Response(200, json={"data": [tx]})))
    assert await p.poll(tracked(addr=GOOD[2])) is None


async def test_mock_adapter_is_deterministic():
    m = MockProvider()
    spec = InvoiceSpec("inv1", "memo", Decimal("5.00"), "USD")
    a, b = await m.create(spec), await MockProvider().create(spec)
    assert a == b and a.pay_amount == Decimal("5.00")
    t = TrackedInvoice(a.provider_ref, "memo", a.pay_address, a.pay_amount, 0)
    assert await m.poll(t) is None
    m.seen(a.provider_ref, confirmations=2)
    assert (await m.poll(t)).status == "confirming"
    m.confirm(a.provider_ref)
    assert (await m.poll(t)).status == "paid"
