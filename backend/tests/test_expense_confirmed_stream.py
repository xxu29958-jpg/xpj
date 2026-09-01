"""Consumer contract for the confirmed expense and offset event stream."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.expense_correction_support import idem


def _manual(
    client: TestClient,
    identity,
    *,
    merchant: str,
    amount_cents: int,
    expense_time: str,
    category: str = "旅游",
    tags: str = "旅行",
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "tags": tags,
            "expense_time": expense_time,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _offset(
    client: TestClient,
    identity,
    expense: dict,
    *,
    kind: str,
    accounting_date: str,
    amount_cents: int | None = None,
) -> dict:
    payload = {
        "kind": kind,
        "accounting_date": accounting_date,
        "reason": f"登记{kind}",
        "expected_row_version": expense["row_version"],
    }
    if amount_cents is not None:
        payload["original_amount_minor"] = amount_cents
    response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _stream(client: TestClient, identity, **params: str | int) -> dict:
    response = client.get(
        "/api/expenses/confirmed",
        headers=identity.app_headers,
        params={"timezone": "Asia/Shanghai", **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_offset_stream_filtering_uses_its_date_category_and_root_tags(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="夏日酒店",
        amount_cents=1200,
        expense_time="2026-08-15T04:00:00Z",
    )
    created = _offset(
        client,
        identity,
        expense,
        kind="refund",
        accounting_date="2026-09-03",
        amount_cents=300,
    )
    offset = created["active_offsets"][0]
    correction = client.post(
        f"/api/expenses/{expense['id']}/offsets/{offset['public_id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "original_amount_minor": 300,
            "accounting_date": "2026-09-03",
            "category": "购物",
            "offset_reason": "退款归到购物",
            "correction_reason": "更正退款归属",
            "expected_row_version": offset["row_version"],
        },
    )
    assert correction.status_code == 201, correction.text

    september = _stream(client, identity, month="2026-09", category="购物", tag="旅行")
    assert september["total"] == 1
    entry = september["items"][0]
    assert entry["entry_kind"] == "offset"
    assert entry["kind"] == "refund"
    assert entry["stream_date"] == "2026-09-03"
    assert entry["stream_amount_cents"] == -300
    assert entry["root_expense_id"] == expense["id"]
    assert entry["root_expense_public_id"] == expense["public_id"]
    assert entry["root_merchant_label"] == "夏日酒店"
    assert entry["home_currency_code"] == expense["home_currency_code"]
    assert entry["original_currency_code"] == expense["original_currency_code"]
    assert _stream(client, identity, month="2026-09", category="旅游", tag="旅行")["total"] == 0

    august = _stream(client, identity, month="2026-08", category="旅游", tag="旅行")
    root = august["items"][0]
    assert root["entry_kind"] == "expense"
    assert root["stream_date"] == "2026-08-15"
    assert root["stream_amount_cents"] == 1200
    assert root["lineage_status"] == "partially_refunded"
    assert root["lineage_home_net_cents"] == 900


def test_stream_pagination_counts_entries_orders_offsets_and_drops_voided(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="多次退款订单",
        amount_cents=1000,
        expense_time="2026-08-10T04:00:00Z",
    )
    first = _offset(
        client,
        identity,
        expense,
        kind="refund",
        accounting_date="2026-09-02",
        amount_cents=200,
    )
    second = _offset(
        client,
        identity,
        first["root"],
        kind="chargeback",
        accounting_date="2026-09-03",
        amount_cents=100,
    )

    page_one = _stream(client, identity, month="2026-09", page=1, page_size=1)
    page_two = _stream(client, identity, month="2026-09", page=2, page_size=1)
    assert page_one["total"] == page_two["total"] == 2
    assert page_one["items"][0]["kind"] == "chargeback"
    assert page_two["items"][0]["kind"] == "refund"

    chargeback = next(item for item in second["active_offsets"] if item["kind"] == "chargeback")
    voided = client.post(
        f"/api/expenses/{expense['id']}/offsets/{chargeback['public_id']}/voids",
        headers=idem(identity.app_headers),
        json={"void_reason": "拒付登记有误", "expected_row_version": chargeback["row_version"]},
    )
    assert voided.status_code == 201, voided.text
    remaining = _stream(client, identity, month="2026-09")
    assert remaining["total"] == 1
    assert remaining["items"][0]["kind"] == "refund"


def test_reversal_stream_is_a_zero_contribution_event_and_zeroes_its_root(
    client: TestClient,
    *,
    identity,
) -> None:
    expense = _manual(
        client,
        identity,
        merchant="重复记账",
        amount_cents=800,
        expense_time="2026-08-20T04:00:00Z",
        tags="复核",
    )
    _offset(
        client,
        identity,
        expense,
        kind="reversal",
        accounting_date="2026-09-04",
    )

    august = _stream(client, identity, month="2026-08", tag="复核")
    root = august["items"][0]
    assert root["entry_kind"] == "expense"
    assert root["lineage_status"] == "reversed"
    assert root["lineage_home_net_cents"] == 0
    assert root["stream_amount_cents"] == 0

    september = _stream(client, identity, month="2026-09", tag="复核")
    reversal = september["items"][0]
    assert reversal["entry_kind"] == "offset"
    assert reversal["kind"] == "reversal"
    assert reversal["stream_date"] == "2026-09-04"
    assert reversal["amount_cents"] == 800
    assert reversal["stream_amount_cents"] == 0
