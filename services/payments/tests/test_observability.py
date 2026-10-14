import json
import logging

from conftest import BUYER, mk


def test_ready_and_no_sensitive_data_in_logs(client, capsys, caplog):
    assert client.get("/ready").json() == {"status": "ready", "service": "payments", "checks": {"database": True}}
    with caplog.at_level(logging.INFO, logger="ff.request"):
        inv = mk(client).json()
        client.get(f"/v1/invoices/{inv['id']}?x=secret-query", headers={**BUYER, "Authorization": "Bearer tok-123"})
        client.post("/v1/payments/webhooks/mock", content=b'{"a":"body-secret"}',
                    headers={"X-FF-Signature": "t=1,v1=sigsecret"})
    out = capsys.readouterr().out + caplog.text
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    assert lines and all(x["service"] == "payments" for x in lines)
    assert any(x["path"] == "/v1/invoices/{invoice_id}" for x in lines)  # route template, not the raw id
    for needle in (inv["pay_address"], inv["memo"], inv["id"], "secret-query", "tok-123", "body-secret",
                   "sigsecret", "admin-secret-test", "whsec-test"):
        assert needle not in out, needle


def test_ready_503_when_db_down(client):
    from ff_payments.obs import ready_response
    assert ready_response("payments", {"database": False}).status_code == 503
