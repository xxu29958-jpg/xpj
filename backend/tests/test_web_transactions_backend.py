"""S-TX release contracts for the Web transaction backend.

These tests pin product facts that span the confirmed list, search, and the
no-JavaScript edit/batch forms.  They intentionally exercise rendered HTTP
responses as well as persisted rows: a green service call alone is not enough
when the browser can display a different month, currency, or conflict state.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api_contract_helpers import patch_expense, web_confirm_expense
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.currency_binding_service import resolve_write_capability
from app.services.spending_contract_service import (
    current_accounting_month,
    shift_month,
)
from app.services.tag_service import sync_expense_tags
from tests._web_bulk_test_support import seed_pending_with_amount


def _month_instant(month: str, *, day: int = 15) -> datetime:
    year, month_number = (int(part) for part in month.split("-"))
    return datetime(year, month_number, day, 12, 0, tzinfo=UTC)


def _seed_confirmed(
    *,
    merchant: str,
    when: datetime | None,
    amount_minor: int = 1200,
    confirmed_at: datetime | None = None,
    created_at: datetime | None = None,
    source: str = "pytest",
    tags: str | None = None,
) -> int:
    with SessionLocal() as db:
        resolve_write_capability(db)
        confirmation_time = confirmed_at or when
        assert confirmation_time is not None
        creation_time = created_at or confirmation_time
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_minor,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_minor,
            exchange_rate_to_cny=Decimal("1"),
            exchange_rate_date=confirmation_time.date(),
            exchange_rate_source="base",
            fx_status="ready",
            merchant=merchant,
            category="餐饮",
            source=source,
            tags=tags,
            status="confirmed",
            expense_time=when,
            confirmed_at=confirmation_time,
            created_at=creation_time,
            updated_at=confirmation_time,
        )
        db.add(expense)
        db.flush()
        if tags:
            sync_expense_tags(db, expense)
        db.commit()
        return expense.id


def _foreign_expense(web_client: TestClient, *, identity, rate: str = "7.0000") -> int:
    rate_response = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": rate,
        },
    )
    assert rate_response.status_code == 200, rate_response.text
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "merchant": "Frozen FX Cafe",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    return int(created.json()["id"])


def _expense_payload(web_client: TestClient, expense_id: int, *, identity) -> dict:
    response = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmed_default_list_and_summary_share_current_month(
    web_client: TestClient,
) -> None:
    current_month = current_accounting_month()
    previous_month = shift_month(current_month, -1)
    _seed_confirmed(merchant="Current Month Cafe", when=_month_instant(current_month))
    _seed_confirmed(merchant="Previous Month Cafe", when=_month_instant(previous_month))

    response = web_client.get("/web/confirmed?ledger_id=owner")

    assert response.status_code == 200, response.text
    assert "Current Month Cafe" in response.text
    assert "Previous Month Cafe" not in response.text
    assert (
        f'<span class="sr-only">{current_month} 合计 </span>¥12.00'
        in response.text
    )
    assert f"{current_month} · 共 1 笔 ·" in response.text


def test_confirmed_list_and_summary_share_configured_accounting_timezone(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.spending_contract_service as spending_contract

    monkeypatch.setattr(
        spending_contract,
        "get_settings",
        lambda: SimpleNamespace(ocr_default_timezone="America/New_York"),
    )
    # 2026-05-01 00:30Z is still April in New York but already May in Shanghai.
    _seed_confirmed(
        merchant="Timezone Boundary Cafe",
        when=datetime(2026, 5, 1, 0, 30, tzinfo=UTC),
    )

    response = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05")

    assert response.status_code == 200, response.text
    assert "Timezone Boundary Cafe" not in response.text
    assert "2026-05 · 共 0 笔 ·" in response.text


def test_confirmed_native_snapshot_updates_without_javascript(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "21.00", "Native Snapshot Cafe", identity=identity
    )
    assert web_confirm_expense(
        web_client, expense_id, identity=identity
    ).status_code in {303, 307}
    before = _expense_payload(web_client, expense_id, identity=identity)
    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200, page.text
    bulk_form = re.search(
        r'<form id="bulk-form".*?</form>',
        page.text,
        flags=re.DOTALL,
    )
    assert bulk_form is not None, page.text
    assert 'name="csrf_token" value="' in bulk_form.group(0)
    assert "data-bulk-enhanced" not in bulk_form.group(0)
    idempotency = re.search(
        r'name="idempotency_key" value="([^"]+)"',
        bulk_form.group(0),
    )
    assert idempotency is not None, bulk_form.group(0)

    response = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_snapshot": f"{expense_id}:{before['row_version']}",
            "category": "家庭采购",
            "reason": "批量更正分类",
            "idempotency_key": idempotency.group(1),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["category"] == "家庭采购"


def test_confirmed_separator_only_tags_fail_without_clearing_existing_tags(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "21.00", "Keep Tags Cafe", identity=identity
    )
    tagged = patch_expense(
        web_client,
        expense_id,
        headers=identity.app_headers,
        fields={"tags": "保留"},
    )
    assert tagged.status_code == 200, tagged.text
    assert web_confirm_expense(
        web_client, expense_id, identity=identity
    ).status_code in {303, 307}
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_tags",
            "ledger_id": "owner",
            "expense_snapshot": f"{expense_id}:{before['row_version']}",
            "tags": ",，，；",
            "reason": "批量更正标签",
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert "请填写标签" in response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["tags"] == "保留"


def test_confirmed_mixed_snapshot_mismatch_fails_closed_in_place(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "22.00", "Mixed Snapshot Cafe", identity=identity
    )
    assert web_confirm_expense(
        web_client, expense_id, identity=identity
    ).status_code in {303, 307}
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": str(expense_id),
            "expected_row_version": str(before["row_version"]),
            "expense_snapshot": f"{expense_id}:{before['row_version'] + 1}",
            "category": "不应落库",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422, response.text
    assert "页面已过期" in response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["category"] == before["category"]


def test_web_edit_ignores_mutable_rate_and_preserves_frozen_fx_snapshot(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id = _foreign_expense(web_client, identity=identity)
    before = _expense_payload(web_client, expense_id, identity=identity)
    assert before["exchange_rate_to_cny"] == "7.00000000"

    changed_rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "8.0000",
        },
    )
    assert changed_rate.status_code == 200, changed_rate.text
    monkeypatch.setattr(
        "app.services.expense_service._update_currency.apply_currency_payload",
        lambda *_args, **_kwargs: pytest.fail(
            "a frozen expense edit must not resolve a mutable FX rate"
        ),
    )

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "外币金额录错",
            "idempotency_key": str(uuid4()),
            "expected_row_version": str(before["row_version"]),
            "original_currency": "USD",
            "amount_yuan": "124.00",
            "merchant": "Frozen FX Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["original_currency_code"] == "USD"
    assert after["original_amount_minor"] == 12400
    assert after["exchange_rate_to_cny"] == before["exchange_rate_to_cny"]
    assert after["exchange_rate_date"] == before["exchange_rate_date"]
    assert after["exchange_rate_source"] == before["exchange_rate_source"]
    assert after["amount_cents"] == 86800


def test_api_amount_correction_preserves_frozen_rate_snapshot(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _foreign_expense(web_client, identity=identity)
    before = _expense_payload(web_client, expense_id, identity=identity)
    changed_rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "8.0000",
        },
    )
    assert changed_rate.status_code == 200, changed_rate.text

    response = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": before["row_version"],
            "reason": "外币金额录错",
            "original_currency_code": "USD",
            "original_amount_minor": 12400,
        },
    )

    assert response.status_code == 201, response.text
    after = response.json()["expense"]
    assert after["exchange_rate_to_cny"] == before["exchange_rate_to_cny"]
    assert after["exchange_rate_date"] == before["exchange_rate_date"]
    assert after["exchange_rate_source"] == before["exchange_rate_source"]
    assert after["amount_cents"] == 86800


def test_original_amount_change_recomputes_items_sum_status(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _foreign_expense(web_client, identity=identity)
    before = _expense_payload(web_client, expense_id, identity=identity)
    assert before["amount_cents"] == 86415
    seeded = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": before["row_version"],
            "reason": "补录小票明细",
            "items": [
                {
                    "name": "整单",
                    "kind": "product",
                    "amount_cents": before["amount_cents"],
                    "category": "餐饮",
                }
            ],
        },
    )
    assert seeded.status_code == 201, seeded.text
    current = seeded.json()["expense"]
    seeded_items = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert seeded_items.status_code == 200, seeded_items.text
    assert seeded_items.json()["items_sum_status"] == "matched"

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "外币金额录错",
            "idempotency_key": str(uuid4()),
            "expected_row_version": str(current["row_version"]),
            "original_currency": "USD",
            "amount_yuan": "124.00",
            "merchant": "Frozen FX Cafe",
            "category": "餐饮",
            "note": "",
            "tags": "",
            "item_public_id": seeded_items.json()["items"][0]["public_id"],
            "item_name": "整单",
            "item_kind": "product",
            "item_quantity": "",
            "item_unit_price_yuan": "",
            "item_amount_yuan": "864.15",
            "item_category": "餐饮",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    items = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert items.status_code == 200, items.text
    assert items.json()["items_sum_status"] == "mismatch_known"
