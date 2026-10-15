from conftest import BUYER, DEAL, make_settings, mk
from fastapi.testclient import TestClient

from ff_payments.clients.deals import MockDealClient
from ff_payments.main import create_app
from ff_payments.providers.mock import MockProvider

TOK = {"X-Internal-Token": "s3cret"}


def test_export_only_ledger_untouched_and_404_for_non_internal():
    app = create_app(make_settings(internal_token="s3cret"), provider=MockProvider(), deals=MockDealClient({"deal_1": DEAL}))
    with TestClient(app, headers=TOK) as c:
        assert c.post("/v1/internal/users/buyer1/export", headers={"X-Internal-Token": "x"}).status_code == 404
        assert c.delete("/v1/internal/users/buyer1/data", headers={"X-Internal-Token": ""}).status_code == 404
        inv = mk(c, memo="my private note").json()
        exp = c.post("/v1/internal/users/buyer1/export").json()
        assert [i["id"] for i in exp["data"]["invoices"]] == [inv["id"]]
        d = c.delete("/v1/internal/users/buyer1/data").json()
        assert d["counts"] == {"memos_cleared": 1} and "ledger_entries" in d["retained"]
        assert c.delete("/v1/internal/users/buyer1/data").json()["counts"] == {"memos_cleared": 0}
        after = c.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()
        assert after["status"] == inv["status"] and after["amount"] == inv["amount"]  # financial record intact
        assert c.post("/v1/internal/users/buyer1/export").json()["data"]["invoices"][0]["user_memo"] is None


def test_export_hides_the_payers_memo_from_the_payee():
    app = create_app(make_settings(internal_token="s3cret"), provider=MockProvider(), deals=MockDealClient({"deal_1": DEAL}))
    with TestClient(app, headers=TOK) as c:
        inv = mk(c, memo="payer only note").json()
        payee = inv["payee"]
        assert payee and payee != "buyer1"
        mine = c.post("/v1/internal/users/buyer1/export").json()["data"]["invoices"][0]
        theirs = c.post(f"/v1/internal/users/{payee}/export").json()["data"]["invoices"]
        assert mine["user_memo"] == "payer only note"
        assert theirs and all(i["user_memo"] is None and "payer_user_id" not in i for i in theirs)
