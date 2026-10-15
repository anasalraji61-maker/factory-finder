import time

import pytest

URL = "/v1/references/detect"


def cands(client, q):
    r = client.get(URL, params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()["candidates"]


def types(cs):
    return {c["type"]: c for c in cs}


def test_valid_container_is_ambiguous_with_bl_so_medium(client):
    t = types(cands(client, "csqu 305438-3"))
    assert t["container"]["normalized"] == "CSQU3054383"
    assert t["container"]["confidence"] == "medium"
    assert t["container"]["note"]


def test_invalid_container_not_reported(client):
    assert "container" not in types(cands(client, "CSQU3054384"))


def test_awb_overlaps_digit_bl_capped_medium(client):
    cs = cands(client, "176-12345675")
    t = types(cs)
    assert t["awb"]["normalized"].replace("-", "") == "17612345675"
    if len(cs) > 1:
        assert all(c["confidence"] != "high" for c in cs)


@pytest.mark.parametrize("q", ["COSU6012345678", "MAEU123456789", "HLCU1234567890"])
def test_bl_known_prefix_high(client, q):
    cs = cands(client, q)
    assert len(cs) == 1 and cs[0]["type"] == "bl" and cs[0]["confidence"] == "high"


def test_bl_unknown_prefix_medium(client):
    assert types(cands(client, "ABCD12345678"))["bl"]["confidence"] == "medium"


def test_multiple_candidates_never_high(client):
    for q in ["CSQU3054383", "17612345675", "9074729", "MSCU6398706"]:
        cs = cands(client, q)
        if len(cs) > 1:
            assert all(c["confidence"] in ("medium", "low") for c in cs)


def test_imo(client):
    assert types(cands(client, "IMO 9074729"))["vessel_imo"]["normalized"] == "9074729"


@pytest.mark.parametrize("q", ["!!!???", "12", "\u0645\u0631\u062d\u0628\u0627", "<script>alert(1)</script>"])
def test_garbage_is_empty(client, q):
    assert cands(client, q) == []


def test_wordlike_text_is_at_most_a_medium_bl_guess(client):
    assert all(c["type"] == "bl" and c["confidence"] == "medium" for c in cands(client, "hello world"))


def test_shape_of_candidate(client):
    c = cands(client, "COSU6012345678")[0]
    assert set(c) == {"type", "confidence", "normalized", "note"}


def test_max_length_ok_and_over_is_422(client):
    assert client.get(URL, params={"q": "A" * 64}).status_code == 200
    assert client.get(URL, params={"q": "A" * 65}).status_code == 422


def test_empty_and_missing_q_422(client):
    assert client.get(URL, params={"q": ""}).status_code == 422
    assert client.get(URL).status_code == 422


@pytest.mark.parametrize("q", ["B/L " * 16, " " * 64, "-" * 64, "COSU" + "\t" * 60, "A1" * 32])
def test_pathological_input_fast(client, q):
    t0 = time.perf_counter()
    r = client.get(URL, params={"q": q})
    assert r.status_code == 200
    assert time.perf_counter() - t0 < 1.0


def test_huge_input_rejected_fast(client):
    t0 = time.perf_counter()
    assert client.get(URL, params={"q": "A" * 5000}).status_code in (414, 422)
    assert time.perf_counter() - t0 < 2.0
