"""Web recovery and timeline consumer for the split-allocation invariant."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.routes._web_expense_fact import _timeline_changes
from tests.web_expense_fact_test_support import create_confirmed, owner_member_id


def test_split_timeline_prioritizes_changed_allocation_over_unchanged_line_count() -> None:
    changes = _timeline_changes(
        {
            "change_kind": "correction",
            "changed_fields": ["splits"],
            "before": {
                "amount_cents": 1_200,
                "splits": [{"amount_cents": 1_200}],
            },
            "after": {
                "amount_cents": 1_200,
                "splits": [{"amount_cents": 1_100}],
            },
        },
        "CNY",
    )

    assert changes == [
        {
            "label": "家庭拆账",
            "before": "已分完",
            "after": "还差 ¥1.00 未分配",
        }
    ]


def test_amount_correction_rejects_overallocation_in_split_fold_and_timeline_shows_partial(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    member_id = owner_member_id()
    initial = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    seeded = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": initial["row_version"],
            "reason": "记录完整家庭分摊",
            "splits": [{"member_id": member_id, "amount_cents": 1234}],
        },
    )
    assert seeded.status_code == 201, seeded.text
    split = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers).json()["splits"][0]

    rejected = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "账单金额应更低",
            "amount_yuan": "10.00",
            "expected_row_version": str(seeded.json()["expense"]["row_version"]),
            "split_public_id": [split["public_id"]],
            "split_member_id": [str(member_id)],
            "split_amount_yuan": ["12.34"],
            "split_note": [""],
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 422, rejected.text
    assert "家庭拆账总额不能超过账单金额" in rejected.text
    assert '<details class="dt-card correction-fold" open>' in rejected.text
    assert 'value="12.34"' in rejected.text

    partial = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "账单金额应更高",
            "amount_yuan": "13.34",
            "expected_row_version": str(seeded.json()["expense"]["row_version"]),
            "split_public_id": [split["public_id"]],
            "split_member_id": [str(member_id)],
            "split_amount_yuan": ["12.34"],
            "split_note": [""],
        },
        follow_redirects=False,
    )
    assert partial.status_code == 303, partial.text
    fact = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert fact.status_code == 200, fact.text
    assert "家庭拆账" in fact.text
    assert "已分完" in fact.text
    assert "还差 ¥1.00 未分配" in fact.text
