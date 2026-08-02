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

import pytest
from api_contract_helpers import patch_expense, web_confirm_expense
from fastapi.testclient import TestClient

import app.routes._web_expense_edit_command as edit_command
from app.database import SessionLocal
from app.models import Expense
from app.schemas import ExpenseItemReplaceRequest, ExpenseItemRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.receipt_item_service import replace_expense_items
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
    assert f'<span class="lh-month">{current_month}</span>' in response.text
    assert "<b>1</b> 笔" in response.text


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
    assert "<b>0</b> 笔" in response.text


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
    assert "<noscript>" in page.text

    response = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_snapshot": f"{expense_id}:{before['row_version']}",
            "category": "家庭采购",
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
    import app.routes.web_expense_edit as web_expense_edit_route

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
    original_update = web_expense_edit_route.update_expense
    assert edit_command.update_expense is original_update
    update_calls = 0

    def _counted_update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        return original_update(*args, **kwargs)

    monkeypatch.setattr(web_expense_edit_route, "update_expense", _counted_update)
    monkeypatch.setattr(
        "app.services.expense_service._update_currency.apply_currency_payload",
        lambda *_args, **_kwargs: pytest.fail(
            "a frozen expense edit must not resolve a mutable FX rate"
        ),
    )

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
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
    assert update_calls == 1
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

    response = patch_expense(
        web_client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "original_currency_code": "USD",
            "original_amount_minor": 12400,
        },
    )

    assert response.status_code == 200, response.text
    after = response.json()
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
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        replaced = replace_expense_items(
            db,
            expense_id,
            "owner",
            ExpenseItemReplaceRequest(
                expected_row_version=expense.row_version,
                items=[
                    ExpenseItemRequest(
                        name="整单",
                        amount_cents=expense.amount_cents,
                        category="餐饮",
                    )
                ],
            ),
        )
        assert replaced.items_sum_status == "matched"
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
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
    items = web_client.get(
        f"/api/expenses/{expense_id}/items",
        headers=identity.app_headers,
    )
    assert items.status_code == 200, items.text
    assert items.json()["items_sum_status"] == "mismatch_known"


def test_edit_confirm_atomically_saves_submitted_facts_before_confirmation(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "10.00", "Before Confirm", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(before["row_version"]),
            "save_before_confirm": "1",
            "original_currency": "CNY",
            "amount_yuan": "12.34",
            "merchant": "Saved Then Confirmed",
            "category": "餐饮",
            "note": "权威表单",
            "tags": "家庭",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["status"] == "confirmed"
    assert after["amount_cents"] == 1234
    assert after["merchant"] == "Saved Then Confirmed"
    assert after["note"] == "权威表单"
    assert after["tags"] == "家庭"


def test_edit_confirm_rolls_back_form_edits_when_confirmation_fails(
    web_client: TestClient,
    *,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 1000,
            "merchant": "Before Failed Confirm",
            "category": "餐饮",
            "expense_time": "2040-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    before = _expense_payload(web_client, expense_id, identity=identity)

    response = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(before["row_version"]),
            "save_before_confirm": "1",
            "original_currency": "USD",
            "amount_yuan": "10.00",
            "merchant": "Must Roll Back",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 409, response.text
    assert "汇率还没同步完成" in response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after == before
