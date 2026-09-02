"""Web pending-edit conflict presentation and retry safety."""

from __future__ import annotations

from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient

from tests._web_bulk_test_support import seed_pending_with_amount
from tests.test_web_transactions_backend import _expense_payload


def test_web_currency_conflict_keeps_draft_money_in_its_submitted_currency(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "8.00", "Currency Conflict", identity=identity
    )
    stale = _expense_payload(web_client, expense_id, identity=identity)
    assert stale["original_currency_code"] == "CNY"

    changed = patch_expense(
        web_client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "original_currency_code": "USD",
            "original_amount_minor": 800,
        },
    )
    assert changed.status_code == 200, changed.text
    current = changed.json()
    assert current["original_currency_code"] == "USD"

    stale_form = {
        "ledger_id": "owner",
        "expected_row_version": str(stale["row_version"]),
        "original_currency": "CNY",
        "amount_yuan": "8.00",
        "merchant": "Currency Conflict",
        "category": "餐饮",
        "note": "",
        "tags": "",
    }
    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data=stale_form,
        follow_redirects=False,
    )

    assert response.status_code == 409, response.text
    assert "账本现值已经改为" in response.text
    assert "不能直接重试" in response.text
    assert 'name="original_currency" value="CNY"' in response.text
    assert ">CNY<" in response.text
    assert ">USD<" in response.text
    assert (
        f'name="expected_row_version" value="{current["row_version"]}"'
        in response.text
    )

    retry = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={**stale_form, "expected_row_version": str(current["row_version"])},
        follow_redirects=False,
    )
    assert retry.status_code == 409, retry.text

    fragment = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            **stale_form,
            "expected_row_version": str(current["row_version"]),
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert fragment.status_code == 409, fragment.text
    assert 'name="original_currency" value="CNY"' in fragment.text
    assert "不能直接重试" in fragment.text

    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["original_currency_code"] == "USD"
    assert after["original_amount_minor"] == 800
