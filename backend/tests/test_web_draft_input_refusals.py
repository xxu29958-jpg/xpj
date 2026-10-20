"""Draft input the server refuses before any commit is a final refusal.

The browser draft then offers to check the current record and keep editing, instead of
only replaying the same original or discarding what was already typed.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Expense, ExpenseSplit, LedgerAuditLog, RecurringItem, RecurringItemRevision
from app.services.currency_binding_service import resolve_write_capability
from app.services.idempotency import claim_idempotency_key
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._web_expense_review_test_support import _run_review_page
from tests._web_expense_review_test_support import review_browser as review_browser
from tests._web_native_form_support import hidden_post_forms
from tests._web_recurring_test_support import open_recurring_form, seed_observed_item
from tests.test_web_expense_detail_v1_slice import _owner_member_id, _seed_pending_expense
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web


def _row_version(client: TestClient, identity, expense_id: int) -> str:
    return str(client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["row_version"])


def _refusal(resp) -> tuple[str, str]:
    assert resp.status_code >= 400, resp.text
    return resp.json()["error"], resp.json()["draft_result"]


def _stored_facts_and_originals():
    with SessionLocal() as db:
        return {model.__tablename__: [dict(row) for row in db.execute(select(model.__table__).order_by(model.id)).mappings()]
            for model in (Expense, ExpenseSplit, LedgerAuditLog, RecurringItem, RecurringItemRevision, ApiIdempotencyKey)}


@pytest.mark.real_db
@pytest.mark.parametrize("operation", ["missing-amount", "missing-amount-save"])
def test_missing_confirmation_amount_stays_editable_then_preserves_lost_reply_recovery(
    review_browser, confirmation_store, tmp_path, operation,
):
    client, _ = review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, 42)
        expense.amount_cents = expense.original_amount_minor = None
        expense.original_currency_code = "CNY"
        expense.exchange_rate_to_cny = Decimal("1")
        expense.exchange_rate_source = "base"
        db.commit()
    result = _run_review_page(client, tmp_path, f"/web/expenses/42/edit?ledger_id=owner&probe={operation}")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["missing_amount_editable"] and result["original_removed"]
    saving = operation == "missing-amount-save"
    assert result["blank_draft_saved" if saving else "receipt_visible"]
    first, replay = result["requests"]
    assert first == replay
    assert dict(first["fields"])["amount_yuan"] == ("" if saving else "0.00")
    with confirmation_store() as db:
        expense = db.get(Expense, 42)
        assert (expense.amount_cents, expense.status, expense.row_version) == (
            None if saving else 0, "pending" if saving else "confirmed", 5 if saving else 6)


def test_confirming_without_an_amount_is_a_final_refusal(web_client: TestClient, *, identity) -> None:
    upload = web_client.post(f"/u/{identity.upload_key}", headers={"Content-Type": "image/png"}, content=PNG_BYTES)
    assert upload.status_code == 200, upload.text
    expense_id = int(upload.json()["id"])
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=pending")
    scope = re.search(r'name="draft_scope" value="([^"]*)"', page.text)
    key = re.search(r'name="idempotency_key" value="([^"]+)"', page.text)
    assert scope and key
    before = _stored_facts_and_originals()
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "idempotency_key": key.group(1),
            "draft_scope": unescape(scope.group(1)),
            "save_before_confirm": "1",
            "amount_yuan": "",
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == ("amount_required", "rejected")
    assert _stored_facts_and_originals() == before
    corrected = {"ledger_id": "owner", "expected_row_version": _row_version(web_client, identity, expense_id),
        "idempotency_key": str(uuid4()), "draft_scope": unescape(scope.group(1)),
        "save_before_confirm": "1", "amount_yuan": "1.00"}
    accepted = web_client.post(f"/web/expenses/{expense_id}/confirm", data=corrected,
        headers={"Accept": "application/json"}, follow_redirects=False)
    assert accepted.status_code == 303, accepted.text
    committed = _stored_facts_and_originals()
    # The first reply may be lost; exact original replay must return its receipt.
    replay = web_client.post(f"/web/expenses/{expense_id}/confirm", data=corrected,
        headers={"Accept": "application/json"}, follow_redirects=False)
    assert replay.status_code == 303 and replay.headers["location"] == accepted.headers["location"]
    receipt = web_client.get(replay.headers["location"])
    assert receipt.status_code == 200 and "这张，记好了" in receipt.text
    changed = web_client.post(f"/web/expenses/{expense_id}/confirm", data={**corrected, "amount_yuan": "2.00"},
        headers={"Accept": "application/json"})
    assert _refusal(changed) == ("idempotency_key_reused", "blocked")
    assert _stored_facts_and_originals() == committed
    with SessionLocal() as db:
        assert (db.get(Expense, expense_id).amount_cents, db.get(Expense, expense_id).status) == (100, "confirmed")


def test_family_shares_above_the_bill_are_a_final_refusal(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense(amount_cents=5000)
    before = _stored_facts_and_originals()
    resp = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "split_member_id": [str(_owner_member_id())],
            "split_amount_yuan": ["80.00"],
            "split_note": [""],
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == ("expense_split_total_exceeds_parent", "rejected")
    assert _stored_facts_and_originals() == before


@pytest.mark.parametrize("rate", ["0", "0.047826123456"])
@pytest.mark.parametrize("original_pending", [False, True])
def test_an_unusable_manual_rate_preserves_any_unresolved_original(
    web_client: TestClient, *, identity, rate: str, original_pending: bool,
) -> None:
    key = str(uuid4())
    with SessionLocal() as db:
        now = now_utc()
        expense = Expense(
            tenant_id="owner",
            amount_cents=None,
            home_currency_code="CNY",
            original_currency_code="JPY",
            original_amount_minor=1200,
            merchant="东京便利店",
            category="餐饮",
            note="",
            source="manual",
            raw_text="",
            status="pending",
            fx_status="pending",
            expense_time=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
        if original_pending:
            claim_idempotency_key(db, tenant_id="owner", idempotency_key=key, operation="patch_expense",
                target_type="expense", target_id=str(expense_id), request_fingerprint="unresolved-original-intent")
            db.commit()
    before = _stored_facts_and_originals()
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "amount_yuan": "1200",
            "original_currency": "JPY",
            "manual_exchange_rate": rate,
            "idempotency_key": key,
            "merchant": "东京便利店",
            "category": "餐饮",
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == (("idempotency_key_reused", "blocked") if original_pending else ("exchange_rate_invalid", "rejected"))
    assert _stored_facts_and_originals() == before


def test_saving_an_unchanged_fixed_expense_is_a_final_refusal(web_client: TestClient) -> None:
    public_id = seed_observed_item(merchant="宽带", source="manual", occurrence_count=0)
    listing = web_client.get("/web/recurring?ledger_id=owner&month=2026-05")
    action = f"/web/recurring/{public_id}/edit"
    fields = hidden_post_forms(open_recurring_form(web_client, listing, public_id=public_id).text)[action]
    fields.update(
        merchant="宽带", baseline_amount_yuan="20.00", next_expected_date="2026-09-08", home_currency_code="CNY"
    )
    before = _stored_facts_and_originals()
    resp = web_client.post(action, data=fields, headers={"Accept": "application/json"})
    assert _refusal(resp) == ("recurring_item_no_changes", "rejected")
    assert _stored_facts_and_originals() == before
