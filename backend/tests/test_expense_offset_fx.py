"""Foreign-currency refunds and reversals preserve historical exchange-rate facts."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests._runtime_protocol import negotiated_headers
from tests.expense_correction_support import idem


def test_foreign_refund_uses_accounting_date_rate_and_freezes_snapshot(
    client: TestClient,
    *,
    identity,
) -> None:
    original_rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 0,
            "currency_code": "USD", "home_currency_code": "CNY",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7",
            "source": "manual",
        },
    )
    assert original_rate.status_code == 200, original_rate.text
    refund_rate = client.put(
        "/api/exchange-rates/USD/2026-05-05",
        headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 0,
            "currency_code": "USD", "home_currency_code": "CNY",
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
            "client_ref": str(uuid4()),
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
        headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 0,
            "currency_code": "USD", "home_currency_code": "CNY",
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
            "client_ref": str(uuid4()),
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


def test_foreign_reversal_reuses_root_snapshot_without_a_new_rate(
    client: TestClient,
    *,
    identity,
) -> None:
    seeded = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 0,
            "currency_code": "USD", "home_currency_code": "CNY",
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
            "client_ref": str(uuid4()),
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
    assert offset["stream_amount_cents"] == 0
    assert offset["exchange_rate_to_cny"] == "7.00000000"
    assert offset["exchange_rate_date"] == "2026-05-04"
    assert offset["exchange_rate_source"] == "manual"
    assert body["financial_summary"] == {
        "gross_original_minor": 10000,
        "gross_home_amount_cents": 70000,
        "root_stream_amount_cents": 0,
        "active_refunded_original_minor": 0,
        "remaining_refundable_original_minor": 0,
        "lineage_home_net_cents": 0,
        "fx_difference_cents": 0,
        "status": "reversed",
    }
