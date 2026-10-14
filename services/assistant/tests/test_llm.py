import json

import httpx
from pydantic import SecretStr

from ff_assistant.config import Settings
from ff_assistant.domain.text import detect_language
from ff_assistant.llm import HttpLlm, LlmError, MockLlm, build_llm, numbers_in
from ff_assistant.service import Assistant


def _settings(**kw) -> Settings:
    base = {"clients": "mock", "llm": "anthropic", "llm_api_key": SecretStr("sk-test-SECRET"), "llm_min_confidence": 1.0}
    return Settings(**{**base, **kw})


def _http(handler, **kw) -> tuple[HttpLlm, Settings, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    s = _settings(**kw)
    return HttpLlm(s, transport=httpx.MockTransport(h)), s, seen


def _reply(text: str):
    return lambda req: httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_defaults_off_and_build():
    assert Settings().llm == "off" and build_llm(Settings()) is None
    assert isinstance(build_llm(Settings(llm="mock")), MockLlm)
    assert build_llm(Settings(llm="anthropic")) is None  # no key -> off


async def test_http_request_shape_and_key_not_leaked():
    llm, s, seen = _http(_reply("{}"))
    assert await llm.complete("sys", "hi", 50) == "{}"
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages" and req.headers["x-api-key"] == "sk-test-SECRET"
    assert body["max_tokens"] == 50 and body["system"] == "sys" and body["messages"][0]["content"] == "hi"
    assert "SECRET" not in repr(llm) and "SECRET" not in repr(s)


async def test_http_errors_become_llm_error_without_key():
    llm, _, _ = _http(lambda r: httpx.Response(500, json={}))
    try:
        await llm.complete("s", "u", 10)
    except LlmError as e:
        assert "SECRET" not in str(e)
    else:
        raise AssertionError("expected LlmError")


async def test_low_confidence_fallback_uses_llm_patch(clients):
    patch = json.dumps({"intent": "search", "kind": "product", "query": "plastic granules", "keywords": ["plastic", "granules"]})
    llm, s, seen = _http(_reply(f"```json\n{patch}\n```"))
    a = Assistant(clients, s, llm=llm)
    r = await a.handle("get me some stuff")
    assert seen and r.parsed_query.query == "plastic granules"
    assert clients.sourcing.calls[0]["q"] == "plastic granules"


async def test_high_confidence_does_not_call_llm(clients):
    llm = MockLlm()
    a = Assistant(clients, _settings(llm_min_confidence=0.5), llm=llm)
    await a.handle("I need plastic granules from China to Baghdad")
    assert llm.calls == []


async def test_invalid_llm_json_falls_back_to_rules(clients):
    base = await Assistant(clients, _settings()).handle("get me some stuff")
    for bad in ["not json at all", "[1,2]", '{"intent": "track"}', '{"kind": "spaceship"}', '{"keywords": "x"}',
                '{"query": ' + '"' + "x" * 500 + '"}', '{"intent": "search", "condition": 5}']:
        a = Assistant(clients, _settings(), llm=MockLlm(bad))
        r = await a.handle("get me some stuff")
        assert r.parsed_query == base.parsed_query, bad


async def test_llm_timeout_and_error_fall_back(clients):
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    llm, s, _ = _http(boom)
    r = await Assistant(clients, s, llm=llm).handle("get me some stuff")
    base = await Assistant(clients, s).handle("get me some stuff")
    assert r.parsed_query == base.parsed_query


async def test_llm_cannot_inject_ids_or_figures(clients):
    llm = MockLlm(json.dumps({"query": "pipes", "supplier_id": "sup_x", "budget": {"amount": "1", "currency": "USD"}}))
    r = await Assistant(clients, _settings(), llm=llm).handle("get me some stuff")
    assert r.parsed_query.supplier_id is None and r.parsed_query.budget is None


async def test_rewrite_preserves_numbers(clients):
    text = "I need plastic granules from China to Baghdad"
    plain = await Assistant(clients, _settings(llm_min_confidence=0.5)).handle(text)
    nums = numbers_in(plain.answer_text)
    s = _settings(llm_min_confidence=0.5, llm_rewrite=True)
    friendly = MockLlm(lambda sys, user: "Great news! " + user)
    r = await Assistant(clients, s, llm=friendly).handle(text)
    assert r.answer_text.startswith("Great news!") and numbers_in(r.answer_text) == nums


async def test_rewrite_with_changed_numbers_is_rejected(clients):
    text = "I need plastic granules from China to Baghdad"
    plain = await Assistant(clients, _settings(llm_min_confidence=0.5)).handle(text)
    s = _settings(llm_min_confidence=0.5, llm_rewrite=True)
    for evil in [lambda sy, u: u.replace("1", "7", 1), lambda sy, u: u + " Only 9 USD!", lambda sy, u: "", lambda sy, u: u * 5]:
        r = await Assistant(clients, s, llm=MockLlm(evil)).handle(text)
        assert r.answer_text == plain.answer_text


def test_numbers_in_normalises_digits_and_commas():
    assert numbers_in("1,234 $ و ١٢٣") == numbers_in("1234 123")


def test_language_detection():
    assert detect_language("I need plastic granules") == "en"
    assert detect_language("أريد حبيبات بلاستيك") == "ar"
    assert detect_language("12345") == "ar"


async def test_english_answers(assistant):
    r = await assistant.handle("I need a used pastry production line from China delivered to Baghdad")
    assert r.parsed_query.language == "en"
    assert "Found" in r.answer_text and "Estimated full landed cost to Baghdad" in r.answer_text
    assert "trust" in r.answer_text.lower()
    assert not any("؀" <= ch <= "ۿ" for ch in r.answer_text)
    q = await assistant.handle("how much to ship 2 tons plastic granules from Ningbo to Basra")
    assert "Basra" in q.answer_text and "estimate" in q.answer_text
    h = await assistant.handle("help")
    assert h.answer_text.startswith("Welcome")
    t = await assistant.handle("is supplier sup_cn_001 trustworthy?")
    assert "Trust score" in t.answer_text
    k = await assistant.handle("track container CSQU3054383")
    assert "container" in k.answer_text


async def test_arabic_stays_default(assistant):
    r = await assistant.handle("أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد")
    assert "لقيت" in r.answer_text
