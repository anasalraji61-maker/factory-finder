from conftest import ALICE, BOB, solid, upload

TOK = {"X-Internal-Token": "s3cret"}


def test_internal_routes_404_for_non_internal(make_client):
    c = make_client(internal_token="s3cret")
    assert c.post("/v1/internal/users/alice/export").status_code == 404
    assert c.delete("/v1/internal/users/alice/data", headers={"X-Internal-Token": "x"}).status_code == 404


def test_export_and_erase_deletes_only_owner_files(make_client):
    c = make_client(internal_token="s3cret")
    a, b = {**ALICE, **TOK}, {**BOB, **TOK}
    ra, rp = upload(c, solid(1), headers=a), upload(c, solid(2), headers=a, kind="verification")
    rb = upload(c, solid(3), headers=b)
    assert ra.status_code == rp.status_code == rb.status_code == 201
    exp = c.post("/v1/internal/users/alice/export", headers=TOK).json()
    assert {f["id"] for f in exp["data"]["files"]} == {ra.json()["id"], rp.json()["id"]}
    assert c.delete("/v1/internal/users/alice/data", headers=TOK).json()["counts"] == {"files_deleted": 2}
    assert c.delete("/v1/internal/users/alice/data", headers=TOK).json()["counts"] == {"files_deleted": 0}
    path = ra.json()["url"].removeprefix("https://api.example.test") if ra.json()["url"].startswith("http") else ra.json()["url"]
    assert c.get(path, headers=TOK).status_code == 404
    assert c.get(rb.json()["url"].removeprefix("https://api.example.test"), headers=TOK).status_code == 200
    assert not list((c.root).glob(f"*{ra.json()['id']}*"))
