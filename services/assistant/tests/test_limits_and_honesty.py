"""Answer length cap, per-user burst rate limit, Arabic fallback for unsupported languages, no order claims."""

import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.domain.parser import parse
from ff_assistant.domain.text import clean_text, detect_language
from ff_assistant.main import create_app
from ff_assistant.service import Assistant

CLAIM = re.compile(r"(?i)(order (has been |was |is )?(placed|confirmed|created|submitted)|purchase (completed|confirmed)"
                   r"|تم (تقديم|إنشاء|تأكيد|إرسال|شراء|وضع) ال?(طلب|شراء)|تم الشراء|اشتريت)")


def run(text, **cfg):
    a = Assistant(build_mock_clients(), Settings(clients="mock", **cfg))
    return asyncio.run(a.handle(text))


# --- length cap ------------------------------------------------------------------------
def test_answer_is_capped():
    full = run("plastic granules to Basra")
    assert len(full.answer_text) > 200
    capped = run("plastic granules to Basra", max_answer_chars=200)
    assert len(capped.answer_text) <= 200
    assert capped.answer_text.endswith("…")


def test_default_cap_is_set():
    assert Settings(clients="mock").max_answer_chars == 1500


# --- unsupported language falls back to Arabic ----------------------------------------
@pytest.mark.parametrize("text", [
    "我想买五吨塑料颗粒，从中国运到巴士拉",
    "Çin'den Basra'ya 5 ton plastik istiyorum",
    "Je voudrais 5 tonnes de plastique à Bassora, café",
    "Мне нужно 5 тонн пластика",
])
def test_unsupported_language_replies_in_arabic(text):
    assert detect_language(clean_text(text)) == "ar"
    assert parse(text).language == "ar"
    assert re.search("[؀-ۿ]", run(text).answer_text)


def test_english_still_english():
    assert detect_language("I need plastic granules") == "en"


# --- never claims an order was placed --------------------------------------------------
@pytest.mark.parametrize("text", [
    "place an order for 5 tons plastic granules to Basra", "buy it now and confirm my order",
    "اطلب لي 5 طن حبيبات بلاستيك إلى البصرة", "اشتري لي هذا المنتج وأكد الطلب", "confirm purchase of sup_cn_001 goods",
])
def test_purchase_requests_get_explicit_no_order_note(text):
    res = run(text)
    assert not CLAIM.search(res.answer_text)
    assert "order_not_placed" in res.warnings
    ar = parse(text).language == "ar"
    assert ("لم أُنشئ أي طلب" in res.answer_text) if ar else ("I have not placed any order" in res.answer_text)


def test_normal_search_has_no_order_note():
    assert "order_not_placed" not in run("plastic granules to Basra").warnings


# --- per-user rate limit ---------------------------------------------------------------
def make_api(**cfg):
    return TestClient(create_app(Settings(clients="mock", **cfg), build_mock_clients()))


def test_rate_limit_per_user_and_isolated():
    api = make_api(rate_limit_per_minute=3)
    body = {"text": "help"}
    for _ in range(3):
        assert api.post("/v1/assistant/query", json=body, headers={"X-User-Id": "u1"}).status_code == 200
    r = api.post("/v1/assistant/query", json=body, headers={"X-User-Id": "u1"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1
    assert api.post("/v1/assistant/query", json=body, headers={"X-User-Id": "u2"}).status_code == 200


def test_rate_limited_requests_do_not_burn_daily_quota():
    api = make_api(rate_limit_per_minute=1, quota_per_day=2)
    h = {"X-User-Id": "u9"}
    assert api.post("/v1/assistant/query", json={"text": "help"}, headers=h).status_code == 200
    for _ in range(5):
        assert api.post("/v1/assistant/query", json={"text": "help"}, headers=h).status_code == 429
    assert api.app.state.quota.usage("u9") == 1
