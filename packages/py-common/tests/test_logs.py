import json
from datetime import UTC, datetime

from ff_common.logs import MASK, format_line, redact, redact_text

NOW = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def test_sensitive_keys_masked_nested():
    out = redact({"Authorization": "Bearer abc", "user": {"password": "p", "name": "n"},
                  "items": [{"api_key": "k"}, {"x": 1}], "X-Api-Key": "z", "Set-Cookie": "s=1"})  # fmt: skip
    assert out["Authorization"] == MASK and out["user"]["password"] == MASK and out["user"]["name"] == "n"
    assert out["items"][0]["api_key"] == MASK and out["items"][1] == {"x": 1}
    assert out["X-Api-Key"] == MASK and out["Set-Cookie"] == MASK


def test_bearer_and_jwt_in_text():
    t = redact_text("hdr Bearer abc.def-ghi== and eyJhbGciOi.eyJzdWIi.sig end")
    assert "abc.def" not in t and "eyJhbGciOi" not in t and "Bearer " + MASK in t


def test_kv_tokens_in_urls():
    t = redact_text("GET /x?token=abc123&password=hunter2&ok=1")
    assert "abc123" not in t and "hunter2" not in t and "ok=1" in t


def test_email_partial():
    assert redact_text("mail anas@example.com now") == "mail a***@e***.com now"
    assert "alice" not in redact_text("a.lice+tag@sub.example.co.uk")


def test_non_str_untouched_and_original_unmodified():
    src = {"n": 3, "t": None, "pw": {"password": "x"}}
    redact(src)
    assert src["pw"]["password"] == "x"
    assert redact(src)["n"] == 3


def test_json_format_shape():
    line = format_line({"service": "s", "status": 200, "user_id": None, "note": "عربي"}, fmt="json", now=NOW)
    assert line == '{"ts":"2026-01-02T03:04:05.678+00:00","level":"INFO","service":"s","status":200,"note":"عربي"}'
    assert json.loads(line)["level"] == "INFO"


def test_json_format_redacts():
    d = json.loads(format_line({"token": "t", "msg": "u@x.io"}, level="WARNING", now=NOW))
    assert d["token"] == MASK and d["msg"] == "u***@x***.io" and d["level"] == "WARNING"


def test_text_format_no_log_injection():
    line = format_line({"path": "/a\nFAKE level=ERROR\r x", "k": None}, fmt="text", now=NOW)
    assert "\n" not in line and "\r" not in line and " " not in line
    assert line.startswith("2026-01-02T03:04:05+00:00 INFO path=/a")
    assert "k=" not in line
