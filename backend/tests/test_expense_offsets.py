"""Refund and reversal facts linked to one confirmed expense."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem, manual_confirmed
from tests.test_bill_split import _seed_receiver
from tests.test_bill_split_security_regressions import _bearer_for_account_ledger


def test_create_offset_requires_authenticated_writer(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=500)

    response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers={"Idempotency-Key": "00000000-0000-4000-8000-000000000001"},
        json={
            "kind": "refund",
            "original_amount_minor": 100,
            "accounting_date": "2026-09-05",
            "reason": "未登录退款",
            "expected_row_version": expense["row_version"],
        },
    )

    assert response.status_code == 401, response.text


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
    receiver_ledger_id = "refund_relationship_receiver"
    receiver_account_id = _seed_receiver(
        name="退款关系收件人",
        ledger_id=receiver_ledger_id,
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
                "cancellation_reason_code": "source_refunded",
            }
        ],
        "accepted_impacts": [],
    }

    sent = client.get("/api/bill-splits/sent", headers=identity.app_headers)
    assert sent.status_code == 200, sent.text
    affected = next(item for item in sent.json()["items"] if item["public_id"] == invitation_public_id)
    assert affected["status"] == "cancelled"
    assert affected["cancellation_reason_code"] == "source_refunded"

    inbox = client.get(
        "/api/bill-splits/inbox",
        headers=_bearer_for_account_ledger(receiver_account_id, receiver_ledger_id),
    )
    assert inbox.status_code == 200, inbox.text
    received = next(item for item in inbox.json()["items"] if item["public_id"] == invitation_public_id)
    assert received["status"] == "cancelled"
    assert received["cancellation_reason_code"] == "source_refunded"


def test_refund_keeps_accepted_split_fact_and_publishes_review_suggestion(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=1200)
    receiver_ledger_id = "refund_accepted_receiver"
    receiver_account_id = _seed_receiver(
        name="已接受退款关系收件人",
        ledger_id=receiver_ledger_id,
    )
    invited = client.post(
        f"/api/expenses/{expense['id']}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 500},
    )
    assert invited.status_code == 200, invited.text
    invitation_public_id = invited.json()["public_id"]
    accepted = client.post(
        f"/api/bill-splits/{invitation_public_id}/accept",
        headers=_bearer_for_account_ledger(receiver_account_id, receiver_ledger_id),
        json={"target_ledger_id": receiver_ledger_id},
    )
    assert accepted.status_code == 200, accepted.text

    before = client.get("/api/bill-splits/sent", headers=identity.app_headers)
    assert before.status_code == 200, before.text
    before_row = next(item for item in before.json()["items"] if item["public_id"] == invitation_public_id)
    assert before_row["source_impact_pending"] is False

    created = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 300,
            "accounting_date": "2026-09-08",
            "reason": "分摊后发生退款",
            "expected_row_version": expense["row_version"],
        },
    )

    assert created.status_code == 201, created.text
    impacts = created.json()["relationship_impacts"]
    assert impacts == {
        "pending_invites_cancelled": [],
        "accepted_impacts": [
            {
                "invitation_public_id": invitation_public_id,
                "source_reason_code": "source_refunded",
                "receiver_display_name": "已接受退款关系收件人",
                "debt_public_id": impacts["accepted_impacts"][0]["debt_public_id"],
                "original_agreed_share_home_minor": 500,
                "suggested_net_share_home_minor": 375,
                "suggested_action": "review_split",
            }
        ],
    }
    assert impacts["accepted_impacts"][0]["debt_public_id"]

    reread = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["relationship_impacts"] == {
        "pending_invites_cancelled": [],
        "accepted_impacts": impacts["accepted_impacts"],
    }

    sent = client.get("/api/bill-splits/sent", headers=identity.app_headers)
    assert sent.status_code == 200, sent.text
    affected = next(item for item in sent.json()["items"] if item["public_id"] == invitation_public_id)
    assert affected["status"] == "accepted"
    assert affected["amount_cents"] == 500
    assert affected["source_impact_pending"] is True


def test_foreign_refund_uses_accounting_date_rate_and_freezes_snapshot(
    client: TestClient,
    *,
    identity,
) -> None:
    original_rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7",
            "source": "manual",
        },
    )
    assert original_rate.status_code == 200, original_rate.text
    refund_rate = client.put(
        "/api/exchange-rates/USD/2026-05-05",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-05",
            "rate_to_cny": "8",
            "source": "manual",
        },
    )
    assert refund_rate.status_code == 200, refund_rate.text
    expense_response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z",
            "merchant": "海外退款订单",
            "category": "购物",
        },
    )
    assert expense_response.status_code == 200, expense_response.text
    expense = expense_response.json()
    assert expense["amount_cents"] == 70000

    created = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 2500,
            "accounting_date": "2026-05-05",
            "reason": "美元订单部分退款",
            "expected_row_version": expense["row_version"],
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    offset = body["active_offsets"][0]
    assert offset["amount_cents"] == 20000
    assert offset["exchange_rate_to_cny"] == "8.00000000"
    assert offset["exchange_rate_date"] == "2026-05-05"
    assert offset["exchange_rate_source"] == "manual"
    assert body["financial_summary"]["lineage_home_net_cents"] == 50000
    assert body["financial_summary"]["fx_difference_cents"] == -2500


def test_foreign_refund_without_accounting_date_rate_refuses_without_mutation(
    client: TestClient,
    *,
    identity,
) -> None:
    seeded = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7",
            "source": "manual",
        },
    )
    assert seeded.status_code == 200, seeded.text
    expense_response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z",
            "merchant": "缺少退款日汇率订单",
            "category": "购物",
        },
    )
    assert expense_response.status_code == 200, expense_response.text
    expense = expense_response.json()

    refused = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 2500,
            "accounting_date": "2026-05-06",
            "reason": "退款日没有汇率",
            "expected_row_version": expense["row_version"],
        },
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "exchange_rate_required"
    reread = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["root"]["row_version"] == expense["row_version"]
    assert reread.json()["active_offsets"] == []


def test_chargeback_is_a_distinct_offset_fact(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=900)

    created = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "chargeback",
            "original_amount_minor": 250,
            "accounting_date": "2026-09-09",
            "reason": "银行卡拒付",
            "expected_row_version": expense["row_version"],
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["active_offsets"][0]["kind"] == "chargeback"
    assert created.json()["financial_summary"]["lineage_home_net_cents"] == 650


def test_foreign_reversal_reuses_root_snapshot_without_a_new_rate(
    client: TestClient,
    *,
    identity,
) -> None:
    seeded = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7",
            "source": "manual",
        },
    )
    assert seeded.status_code == 200, seeded.text
    expense_response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z",
            "merchant": "海外冲销订单",
            "category": "购物",
        },
    )
    assert expense_response.status_code == 200, expense_response.text
    expense = expense_response.json()

    reversed_response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "reversal",
            "accounting_date": "2026-05-09",
            "reason": "原交易已冲销",
            "expected_row_version": expense["row_version"],
        },
    )

    assert reversed_response.status_code == 201, reversed_response.text
    body = reversed_response.json()
    offset = body["active_offsets"][0]
    assert offset["kind"] == "reversal"
    assert offset["original_amount_minor"] == 10000
    assert offset["amount_cents"] == 70000
    assert offset["exchange_rate_to_cny"] == "7.00000000"
    assert offset["exchange_rate_date"] == "2026-05-04"
    assert offset["exchange_rate_source"] == "manual"
    assert body["financial_summary"] == {
        "gross_original_minor": 10000,
        "gross_home_amount_cents": 70000,
        "active_refunded_original_minor": 0,
        "remaining_refundable_original_minor": 0,
        "lineage_home_net_cents": 0,
        "fx_difference_cents": 0,
        "status": "reversed",
    }


def test_offset_create_replays_once_and_stale_new_intent_conflicts(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=1000)
    payload = {
        "kind": "refund",
        "original_amount_minor": 200,
        "accounting_date": "2026-09-10",
        "reason": "重复提交退款",
        "expected_row_version": expense["row_version"],
    }
    key = "00000000-0000-4000-8000-000000000099"

    first = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )
    replay = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )
    stale = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={**payload, "reason": "另一条过期意图"},
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"
    reread = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert len(reread.json()["active_offsets"]) == 1
