"""An unrelated correction cannot adopt a category suggestion as a confirmed fact."""

from uuid import uuid4

import pytest

from tests._web_native_form_support import _NativeForm
from tests.api_contract_helpers import patch_expense, upload_png
from tests.expense_correction_support import idem, revision_history


def _expense_and_rule(client, identity):
    created = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1280,
        "merchant": "原商家", "category": "其他", "expense_time": "2026-05-04T00:30:00Z",
    })
    assert created.status_code == 200, created.text
    expense = created.json()
    assert expense["status"] == "confirmed" and expense["category"] == "其他"
    rule = client.post("/api/rules/categories", headers=idem(identity.app_headers), json={
        "keyword": "财务边界测试商家", "category": "购物", "enabled": True, "priority": 1,
    })
    assert rule.status_code == 200, rule.text
    return expense


@pytest.mark.parametrize("field", ["merchant", "note"])
def test_correction_preserves_category_until_explicitly_changed(client, identity, field):
    expense = _expense_and_rule(client, identity)
    path = f"/api/expenses/{expense['id']}/corrections"
    headers = idem(identity.app_headers)
    payload = {"expected_row_version": expense["row_version"], "reason": "只更正文字",
        field: "财务边界测试商家"}
    corrected = client.post(path, headers=headers, json=payload)
    assert corrected.status_code == 201, corrected.text
    saved = corrected.json()["expense"]
    assert saved["category"] == "其他"
    assert corrected.json()["revision"]["changed_fields"] == [field]
    replayed = client.post(path, headers=headers, json=payload)
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["expense"]["row_version"] == saved["row_version"]
    assert revision_history(client, identity, expense["id"])["total"] == 2
    latest = client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers)
    assert latest.status_code == 200, latest.text
    assert latest.json()["category"] == "其他"
    explicit = client.post(path, headers=idem(identity.app_headers), json={
        "expected_row_version": saved["row_version"], "reason": "明确更正分类", "category": "购物",
    })
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["expense"]["category"] == "购物"
    assert explicit.json()["revision"]["changed_fields"] == ["category"]


def test_web_merchant_correction_preserves_the_reviewed_category(web_client, identity):
    expense = _expense_and_rule(web_client, identity)
    path = f"/web/expenses/{expense['id']}/corrections"
    page = web_client.get(f"/web/expenses/{expense['id']}/correct?ledger_id=owner")
    assert page.status_code == 200, page.text
    form = _NativeForm(page.text, path)
    form.set("merchant", "财务边界测试商家")
    form.set("reason", "只更正商家")
    response = web_client.post(path, data=form.fields, follow_redirects=False)
    assert response.status_code == 303, response.text
    detail = web_client.get(response.headers["location"])
    assert detail.status_code == 200, detail.text
    latest = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers)
    assert latest.status_code == 200, latest.text
    assert latest.json()["merchant"] == "财务边界测试商家"
    assert latest.json()["category"] == "其他"
    history = revision_history(web_client, identity, expense["id"])
    assert history["items"][0]["changed_fields"] == ["merchant"]


def test_pending_edit_still_offers_matching_category(client, identity):
    _expense_and_rule(client, identity)
    pending_id = upload_png(client, identity=identity)
    edited = patch_expense(client, pending_id, headers=identity.app_headers,
        fields={"merchant": "财务边界测试商家", "amount_cents": 1280})
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "pending"
    assert edited.json()["category"] == "购物"
