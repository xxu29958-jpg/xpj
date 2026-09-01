"""Refund and reversal facts linked to one confirmed expense."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem, manual_confirmed
from tests.test_bill_split import _seed_receiver


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
            "accounting_date": "2026-09-05",
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
    assert body["active_offsets"][0]["accounting_date"] == "2026-09-05"

    reread = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert reread.status_code == 200, reread.text
    assert reread.json() == body


def test_fact_bundle_read_resolves_the_same_device_local_ref(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(
        client,
        identity,
        amount_cents=800,
        client_ref="refund-local-read",
    )
    created = client.post(
        "/api/expenses/local:refund-local-read/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 200,
            "accounting_date": "2026-09-06",
            "reason": "本地引用退款",
            "expected_row_version": 0,
        },
    )
    assert created.status_code == 201, created.text

    reread = client.get(
        "/api/expenses/local:refund-local-read/fact-bundle",
        headers=identity.app_headers,
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["root"]["id"] == expense["id"]
    assert reread.json()["financial_summary"]["lineage_home_net_cents"] == 600


def test_refund_cancels_pending_split_and_publishes_relationship_receipt(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=1200)
    receiver_account_id = _seed_receiver(
        name="退款关系收件人",
        ledger_id="refund_relationship_receiver",
    )
    invited = client.post(
        f"/api/expenses/{expense['id']}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 500},
    )
    assert invited.status_code == 200, invited.text
    invitation_public_id = invited.json()["public_id"]

    created = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 300,
            "accounting_date": "2026-09-07",
            "reason": "部分商品退款",
            "expected_row_version": expense["row_version"],
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["relationship_impacts"] == {
        "pending_invites_cancelled": [
            {
                "invitation_public_id": invitation_public_id,
                "reason_code": "source_refunded",
            }
        ],
        "accepted_impacts": [],
    }

    sent = client.get("/api/bill-splits/sent", headers=identity.app_headers)
    assert sent.status_code == 200, sent.text
    affected = next(item for item in sent.json()["items"] if item["public_id"] == invitation_public_id)
    assert affected["status"] == "cancelled"
    assert affected["cancellation_reason_code"] == "source_refunded"
