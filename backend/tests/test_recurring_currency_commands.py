"""Real command/receipt postconditions for recorded recurring money."""

from uuid import uuid4


def test_recurring_original_receipts_survive_later_edits_and_default_currency(client, identity):
    path = "/api/recurring/items"
    original_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    original = {"merchant": "日元订阅", "home_currency_code": "JPY", "baseline_amount_cents": 1200}
    created = client.post(path, headers=original_headers, json=original)
    assert created.status_code == 201, created.json()
    public_id = created.json()["public_id"]
    path += f"/{public_id}"
    edit_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    edit = {"home_currency_code": "JPY", "baseline_amount_cents": 1300, "expected_row_version": 1}
    edited = client.patch(path, headers=edit_headers, json=edit)
    assert edited.status_code == 200, edited.json()
    latest = client.patch(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={**edit, "baseline_amount_cents": 1450, "expected_row_version": 2})
    assert latest.status_code == 200, latest.json()
    replay_create = client.post("/api/recurring/items", headers=original_headers, json=original)
    assert replay_create.status_code == 201, replay_create.json()
    assert replay_create.json() == created.json()
    replay_edit = client.patch(path, headers=edit_headers, json=edit)
    assert replay_edit.status_code == 200, replay_edit.json()
    assert replay_edit.json() == edited.json()
    relabel = client.patch(path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={**edit, "home_currency_code": "CNY", "expected_row_version": 3})
    assert relabel.status_code == 409 and relabel.json()["error"] == "recurring_currency_conflict"
    actual = client.get(path, headers=identity.app_headers)
    assert actual.status_code == 200, actual.json()
    assert (actual.json()["home_currency_code"], actual.json()["baseline_amount_cents"], actual.json()["row_version"]) == ("JPY", 1450, 3)
    archived = client.post(f"{path}/archive", headers=identity.app_headers)
    assert archived.status_code == 200 and archived.json()["home_currency_code"] == "JPY"
    recycled = client.get("/api/recycle-bin", headers=identity.app_headers)
    assert recycled.status_code == 200, recycled.json()
    entry = next(item for item in recycled.json()["items"] if item["title"] == "日元订阅")
    assert "¥1,450" in entry["detail"] and "14.50" not in entry["detail"]
    after_archive = client.post("/api/recurring/items", headers=original_headers, json=original)
    assert after_archive.status_code == 201 and after_archive.json() == created.json()
