"""Refund and reversal facts linked to one confirmed expense."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem, manual_confirmed


def test_refund_keeps_original_fact_and_publishes_net_bundle(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=1280)

    created = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 300,
            "accounting_time": "2026-09-05T10:00:00Z",
            "reason": "退货退款",
            "expected_row_version": expense["row_version"],
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["root"]["amount_cents"] == 1280
    assert body["root"]["row_version"] > expense["row_version"]
    assert body["financial_summary"] == {
        "gross_original_minor": 1280,
        "gross_home_amount_cents": 1280,
        "active_refunded_original_minor": 300,
        "remaining_refundable_original_minor": 980,
        "lineage_home_net_cents": 980,
        "fx_difference_cents": 0,
        "status": "partially_refunded",
    }
    assert len(body["active_offsets"]) == 1
    assert body["active_offsets"][0]["kind"] == "refund"
    assert body["active_offsets"][0]["original_amount_minor"] == 300
    assert body["active_offsets"][0]["amount_cents"] == 300
    assert body["active_offsets"][0]["accounting_time"] == "2026-09-05T10:00:00Z"

    reread = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert reread.status_code == 200, reread.text
    assert reread.json() == body
