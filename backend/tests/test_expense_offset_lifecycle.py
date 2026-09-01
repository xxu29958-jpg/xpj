"""Correction and void lifecycle for persisted refund, chargeback, and reversal facts."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem, manual_confirmed
from tests.test_bill_split import _seed_receiver


def _seed_usd_rate(client: TestClient, identity, rate_date: str, rate: str) -> None:
    response = client.put(
        f"/api/exchange-rates/USD/{rate_date}",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": rate_date,
            "rate_to_cny": rate,
            "source": "manual",
        },
    )
    assert response.status_code == 200, response.text


def _foreign_expense(client: TestClient, identity, merchant: str) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z",
            "merchant": merchant,
            "category": "购物",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_refund(
    client: TestClient,
    identity,
    expense: dict,
    *,
    accounting_date: str = "2026-05-05",
    reason: str = "首次登记",
) -> dict:
    response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 2500,
            "accounting_date": accounting_date,
            "reason": reason,
            "expected_row_version": expense["row_version"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_amount_only_offset_correction_reuses_its_frozen_rate_and_occ_baseline(
    client: TestClient,
    *,
    identity,
) -> None:
    for rate_date, rate in (("2026-05-04", "7"), ("2026-05-05", "8")):
        _seed_usd_rate(client, identity, rate_date, rate)
    expense = _foreign_expense(client, identity, "更正汇率订单")
    created_body = _create_refund(client, identity, expense)
    offset = created_body["active_offsets"][0]
    _seed_usd_rate(client, identity, "2026-05-05", "9")
    payload = {
        "original_amount_minor": 2000,
        "accounting_date": "2026-05-05",
        "category": "购物",
        "offset_reason": "部分商品退款",
        "correction_reason": "更正退款金额",
        "expected_row_version": offset["row_version"],
    }
    key = "00000000-0000-4000-8000-000000000201"

    corrected = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )
    replay = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )

    assert corrected.status_code == 201, corrected.text
    body = corrected.json()
    corrected_offset = body["active_offsets"][0]
    assert corrected_offset["amount_cents"] == 16000
    assert corrected_offset["exchange_rate_to_cny"] == "8.00000000"
    assert corrected_offset["exchange_rate_date"] == "2026-05-05"
    assert corrected_offset["reason"] == "部分商品退款"
    assert corrected_offset["row_version"] == offset["row_version"] + 1
    assert body["root"]["row_version"] > created_body["root"]["row_version"]
    assert body["recent_history"][0]["change_kind"] == "correction"
    assert body["recent_history"][0]["reason"] == "更正退款金额"
    assert replay.status_code == 201, replay.text
    assert replay.json() == body

    stale = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={**payload, "correction_reason": "过期编辑"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_date_changed_offset_correction_requires_and_freezes_the_new_rate(
    client: TestClient,
    *,
    identity,
) -> None:
    for rate_date, rate in (("2026-05-04", "7"), ("2026-05-05", "8")):
        _seed_usd_rate(client, identity, rate_date, rate)
    expense = _foreign_expense(client, identity, "改日退款订单")
    before = _create_refund(client, identity, expense, reason="原退款日")
    offset = before["active_offsets"][0]
    payload = {
        "original_amount_minor": 2500,
        "accounting_date": "2026-05-06",
        "category": "购物",
        "offset_reason": "退款日改为到账日",
        "correction_reason": "原日期填错",
        "expected_row_version": offset["row_version"],
    }
    key = "00000000-0000-4000-8000-000000000202"

    missing_rate = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )
    assert missing_rate.status_code == 409, missing_rate.text
    assert missing_rate.json()["error"] == "exchange_rate_required"
    unchanged = client.get(
        f"/api/expenses/{expense['id']}/fact-bundle",
        headers=identity.app_headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == before

    _seed_usd_rate(client, identity, "2026-05-06", "9")
    corrected = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )

    assert corrected.status_code == 201, corrected.text
    corrected_offset = corrected.json()["active_offsets"][0]
    assert corrected_offset["amount_cents"] == 22500
    assert corrected_offset["exchange_rate_to_cny"] == "9.00000000"
    assert corrected_offset["exchange_rate_date"] == "2026-05-06"


def test_void_offset_restores_net_but_never_resurrects_cancelled_invites(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = manual_confirmed(client, identity, amount_cents=1200)
    receiver_ledger_id = "void_refund_receiver"
    receiver_account_id = _seed_receiver(
        name="撤销退款关系收件人",
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
            "accounting_date": "2026-09-11",
            "reason": "先登记退款",
            "expected_row_version": expense["row_version"],
        },
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    offset = created_body["active_offsets"][0]
    payload = {
        "void_reason": "实际没有发生退款",
        "expected_row_version": offset["row_version"],
    }
    key = "00000000-0000-4000-8000-000000000203"

    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )
    replay = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/voids",
        headers=idem(identity.app_headers, key=key),
        json=payload,
    )

    assert voided.status_code == 201, voided.text
    body = voided.json()
    assert body["active_offsets"] == []
    assert body["financial_summary"]["lineage_home_net_cents"] == 1200
    assert body["financial_summary"]["status"] == "confirmed"
    assert body["relationship_impacts"] == {
        "pending_invites_cancelled": [],
        "accepted_impacts": [],
    }
    assert body["root"]["row_version"] > created_body["root"]["row_version"]
    assert body["recent_history"][0]["change_kind"] == "void"
    assert body["recent_history"][0]["reason"] == "实际没有发生退款"
    assert body["recent_history"][0]["before"]["status"] == "active"
    assert body["recent_history"][0]["after"]["status"] == "voided"
    assert replay.status_code == 201, replay.text
    assert replay.json() == body

    sent = client.get("/api/bill-splits/sent", headers=identity.app_headers)
    assert sent.status_code == 200, sent.text
    invitation = next(item for item in sent.json()["items"] if item["public_id"] == invitation_public_id)
    assert invitation["status"] == "cancelled"
    assert invitation["cancellation_reason_code"] == "source_refunded"
