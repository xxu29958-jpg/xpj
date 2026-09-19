"""Real PostgreSQL/HTTP continuation through older relationship facts."""

from tests._web_native_form_support import hidden_post_forms
from tests.test_web_debt_actions import _create_debt, _headers


def test_older_repayment_page_can_be_reopened_voided_and_replayed(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    first_fact_id = None
    for _ in range(21):
        response = web_client.post(
            f"/api/debts/{public_id}/repayments", headers=_headers(identity),
            json={"amount_cents": 100, "expected_row_version": debt["row_version"]},
        )
        assert response.status_code == 201, response.text
        debt = response.json()
        first_fact_id = first_fact_id or debt["repayment_public_id"]

    newest = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    assert newest.status_code == 200
    assert "共 22 条" in newest.text and "activity_page=2" in newest.text
    assert f'id="repayment-{first_fact_id}"' not in newest.text
    older = web_client.get(f"/web/debts/{public_id}?ledger_id=owner&activity_page=2")
    assert older.status_code == 200
    assert f'id="repayment-{first_fact_id}"' in older.text
    assert "建立往来" in older.text
    focused = web_client.get(f"/web/debts/{public_id}?ledger_id=owner&focus_repayment={first_fact_id}")
    assert focused.status_code == 200
    assert f'id="repayment-{first_fact_id}"' in focused.text and "第 2 页" in focused.text

    action = f"/web/debts/{public_id}/repayment-voids?activity_page=2"
    # The native form supplies the real key, CSRF and OCC fields.
    forms = hidden_post_forms(older.text)
    form = {**forms[action], "repayment_public_id": first_fact_id, "reason": ""}
    original_key = form["idempotency_key"]
    rejected = web_client.post(action, data=form)
    assert rejected.status_code == 422
    retained = hidden_post_forms(rejected.text)[action]
    assert retained["idempotency_key"] == original_key
    assert retained["repayment_public_id"] == first_fact_id
    assert "第 2 页" in rejected.text
    valid = {**retained, "reason": "重复记了这一笔"}
    saved = web_client.post(action, data=valid)
    replay = web_client.post(action, data=valid)
    assert saved.status_code == replay.status_code == 200
    assert "重复记了这一笔" in saved.text
    current = web_client.get(f"/api/debts/{public_id}/activity", headers=identity.app_headers)
    assert current.status_code == 200
    assert current.json()["total"] == 23
    assert sum(item["kind"] == "repayment_void" for item in current.json()["items"]) == 1
