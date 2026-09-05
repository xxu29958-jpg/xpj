"""Web recovery for one pending foreign-currency expense."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _pending_foreign_expense(client: TestClient, *, identity) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "merchant": "Pending FX Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T02:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    expense = response.json()
    assert expense["status"] == "pending"
    assert expense["fx_status"] == "pending"
    return expense


def _edit_form(expense: dict, *, rate: str, key: str) -> dict[str, str]:
    return {
        "ledger_id": "owner",
        "return_to": "pending",
        "expected_row_version": str(expense["row_version"]),
        "idempotency_key": key,
        "original_currency": expense["original_currency_code"],
        "amount_yuan": expense["original_amount"],
        "manual_exchange_rate": rate,
        "merchant": expense["merchant"],
        "category": expense["category"],
        "note": expense["note"] or "",
        "tags": expense["tags"] or "",
        "expense_time": "2026-05-04T10:00",
    }


def test_web_writer_recovers_one_pending_bill_then_reviews_canonical_home_amount(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    edit_url = f"/web/expenses/{expense['id']}/edit?ledger_id=owner"

    full_page = web_client.get(edit_url)
    drawer = web_client.get(f"{edit_url}&fragment=1")
    for response in (full_page, drawer):
        assert response.status_code == 200, response.text
        assert 'name="manual_exchange_rate"' in response.text
        assert "仅用于本笔账单" in response.text
        assert "1 USD" in response.text
        assert "CNY" in response.text
        assert "确认入账" not in response.text

    saved = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=_edit_form(expense, rate="7", key=str(uuid4())),
        follow_redirects=True,
    )
    assert saved.status_code == 200, saved.text
    assert saved.url.path == f"/web/expenses/{expense['id']}/edit"
    assert "汇率已保存" in saved.text
    assert "仍待确认" in saved.text
    assert "≈ ¥864.15" in saved.text
    assert "汇率 1 USD = 7.00000000 CNY" in saved.text
    assert "确认入账" in saved.text

    current = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json()
    assert current["status"] == "pending"
    assert current["fx_status"] == "ready"
    assert current["amount_cents"] == 86415
    assert current["fx_source"] == "manual"
    rates = web_client.get("/api/exchange-rates", headers=identity.app_headers)
    assert rates.status_code == 200, rates.text
    assert rates.json()["items"] == []


def test_web_manual_rate_failure_keeps_complete_form_and_retry_token(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    key = str(uuid4())
    submitted = {
        **_edit_form(expense, rate="0", key=key),
        "merchant": "Uncommitted Merchant",
        "note": "keep this draft",
    }

    refused = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=submitted,
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    assert re.search(r'name="manual_exchange_rate"[^>]*value="0"', refused.text)
    assert re.search(
        rf'name="expected_row_version" value="{expense["row_version"]}"',
        refused.text,
    )
    assert re.search(rf'name="idempotency_key" value="{re.escape(key)}"', refused.text)
    assert "Uncommitted Merchant" in refused.text
    assert "keep this draft" in refused.text

    unchanged = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json()
    assert unchanged["row_version"] == expense["row_version"]
    assert unchanged["merchant"] == expense["merchant"]
    assert unchanged["fx_status"] == "pending"
    assert unchanged["exchange_rate_to_cny"] is None

    retried = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data={**submitted, "manual_exchange_rate": "7"},
        follow_redirects=False,
    )
    assert retried.status_code == 303, retried.text


def test_web_manual_rate_replay_uses_full_original_form_intent(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    key = str(uuid4())
    submitted = {
        **_edit_form(expense, rate="7", key=key),
        "merchant": "Edited Once",
        "note": "same raw intent",
    }

    first = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=submitted,
        follow_redirects=False,
    )
    assert first.status_code == 303, first.text
    after = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json()

    replay = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=submitted,
        follow_redirects=False,
    )
    assert replay.status_code == 303, replay.text
    assert web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json() == after

    reused = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data={**submitted, "merchant": "Different Intent"},
        follow_redirects=False,
    )
    assert reused.status_code == 422, reused.text
    rotated = re.search(r'name="idempotency_key" value="([^"]+)"', reused.text)
    assert rotated is not None
    assert rotated.group(1) != key
    assert "Different Intent" in reused.text
    assert web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json() == after


def test_web_manual_rate_occ_conflict_preserves_draft_against_current_snapshot(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    key = str(uuid4())
    submitted = {
        **_edit_form(expense, rate="7.25", key=key),
        "merchant": "My Stale Merchant",
    }
    concurrent = web_client.patch(
        f"/api/expenses/{expense['id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": expense["row_version"],
            "note": "saved on another device",
        },
    )
    assert concurrent.status_code == 200, concurrent.text

    conflict = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=submitted,
        follow_redirects=False,
    )
    assert conflict.status_code == 409, conflict.text
    assert "My Stale Merchant" in conflict.text
    assert re.search(r'name="manual_exchange_rate"[^>]*value="7.25"', conflict.text)
    assert re.search(
        rf'name="expected_row_version" value="{concurrent.json()["row_version"]}"',
        conflict.text,
    )
    assert re.search(rf'name="idempotency_key" value="{re.escape(key)}"', conflict.text)

    canonical = web_client.get(f"/api/expenses/{expense['id']}", headers=identity.app_headers).json()
    assert canonical["note"] == "saved on another device"
    assert canonical["merchant"] == expense["merchant"]
    assert canonical["fx_status"] == "pending"


def test_web_changed_manual_rate_must_be_saved_and_reviewed_before_confirm(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    saved = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=_edit_form(expense, rate="7", key=str(uuid4())),
        follow_redirects=False,
    )
    assert saved.status_code == 303, saved.text
    previewed = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    assert previewed["status"] == "pending"
    assert previewed["amount_cents"] == 86415

    changed_intent = {
        **_edit_form(previewed, rate="7.25", key=str(uuid4())),
        "save_before_confirm": "1",
    }
    refused = web_client.post(
        f"/web/expenses/{expense['id']}/confirm",
        data=changed_intent,
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    assert "先保存" in refused.text
    assert re.search(
        r'name="manual_exchange_rate"[^>]*value="7.25"', refused.text
    )

    still_previewed = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    assert still_previewed["status"] == "pending"
    assert still_previewed["amount_cents"] == 86415
    assert still_previewed["exchange_rate_to_cny"] == "7.00000000"

    saved_changed = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=changed_intent,
        follow_redirects=False,
    )
    assert saved_changed.status_code == 303, saved_changed.text
    reviewed = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    assert reviewed["status"] == "pending"
    assert reviewed["amount_cents"] == 89501
    assert reviewed["exchange_rate_to_cny"] == "7.25000000"

    confirmed = web_client.post(
        f"/web/expenses/{expense['id']}/confirm",
        data={
            **_edit_form(reviewed, rate="7.25", key=str(uuid4())),
            "save_before_confirm": "1",
        },
        follow_redirects=False,
    )
    assert confirmed.status_code == 303, confirmed.text
    final = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    assert final["status"] == "confirmed"
    assert final["amount_cents"] == 89501


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    (
        ("amount_yuan", "124.45"),
        ("expense_time", "2026-05-05T10:00"),
    ),
)
def test_web_changed_manual_fx_inputs_require_a_new_preview(
    web_client: TestClient,
    identity,
    changed_field: str,
    changed_value: str,
) -> None:
    expense = _pending_foreign_expense(web_client, identity=identity)
    first = web_client.post(
        f"/web/expenses/{expense['id']}/save",
        data=_edit_form(expense, rate="7", key=str(uuid4())),
        follow_redirects=False,
    )
    assert first.status_code == 303, first.text
    previewed = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    changed = {
        **_edit_form(previewed, rate="7", key=str(uuid4())),
        "save_before_confirm": "1",
        changed_field: changed_value,
    }

    refused = web_client.post(
        f"/web/expenses/{expense['id']}/confirm",
        data=changed,
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    assert "请先保存草稿" in refused.text
    current = web_client.get(
        f"/api/expenses/{expense['id']}", headers=identity.app_headers
    ).json()
    assert current["status"] == "pending"
    assert current["amount_cents"] == 86415
    assert current["row_version"] == previewed["row_version"]
