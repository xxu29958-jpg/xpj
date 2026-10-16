"""An accepted confirmation keeps its first result across later financial edits.

The actual confirmation command, original receipt and rollback use PostgreSQL.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense
from app.schemas import ExpenseConfirmRequest
from app.services import expense_review_command_service as owner
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store


def _confirm(db, **changes):
    return owner.confirm_expense_submission(db, expense_id=42, tenant_id="owner", expected_row_version=4,
        request_expected_row_version=4, idempotency_key="original-confirm", intent_body={}, update_payload=None,
        require_idempotency=True, **changes)


def test_confirmation_and_receipt_roll_back_together(confirmation_store, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError("injected receipt failure")

    monkeypatch.setattr(owner, "mark_idempotency_succeeded", fail)
    with confirmation_store() as db, pytest.raises(SQLAlchemyError, match="injected receipt failure"):
        _confirm(db)
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.status, current.row_version, current.fact_revision) == ("pending", 4, 0)
        assert db.scalar(select(ApiIdempotencyKey)) is None


def test_web_original_confirmation_precedes_validation_against_a_later_manual_fx_fact(confirmation_store):
    from app.routes._web_expense_confirm_command import confirm_web_expense
    from app.routes._web_expense_edit_form import WebExpenseEditForm
    from app.routes._web_expense_return_context import ExpenseReturnContext

    form = WebExpenseEditForm(ledger_id="owner", expected_row_version="4", idempotency_key="web-confirm-original",
        save_before_confirm=True, amount_yuan="2850", original_currency="JPY", manual_exchange_rate="0.045123",
        merchant="首次便利店", category="购物", note="", tags="", expense_time=None, fragment=0,
        return_context=ExpenseReturnContext(return_to="pending", return_filter="ready", return_page="2"))
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        current.exchange_rate_source, current.exchange_rate_to_cny = "manual", Decimal("0.045123")
        db.commit()
        first = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=form)
        assert first.error is None
        assert first.receipt.amount_cents == 12860
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        current.exchange_rate_to_cny, current.original_amount_minor = Decimal("0.08"), 4000
        current.amount_cents, current.merchant, current.row_version = 32000, "后来人工更正", 9
        db.commit()
    with confirmation_store() as db:
        replay = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=form)
        assert replay.error is None, replay.error
        assert replay.receipt.model_dump(mode="json") == first.receipt.model_dump(mode="json")
        changed = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=replace(form, amount_yuan="9999"))
        assert changed.error_status == 422 and changed.error_code == "idempotency_key_reused"
        current = db.get(Expense, 42)
        assert (current.amount_cents, current.merchant, current.row_version) == (32000, "后来人工更正", 9)


@pytest.mark.parametrize("currency,minor", [("JPY", 2850), ("CNY", None)])
def test_api_keeps_original_financial_receipt_beside_current_fact_and_original_disposal(confirmation_store, monkeypatch, currency, minor):
    from app.routes import expenses

    def dispose(db, row):
        row.image_deleted_at = row.thumbnail_deleted_at = datetime(2026, 10, 8, tzinfo=UTC)
        db.commit()

    monkeypatch.setattr(owner, "cleanup_after_confirm", dispose)
    monkeypatch.setattr(expenses, "expense_to_response", owner.expense_to_response)
    monkeypatch.setattr(expenses, "resolve_expense_for_mutation", lambda *args, **kwargs: (42, 4))
    auth = SimpleNamespace(tenant_id="owner", device_id=None, account_id=None)

    def submit(db):
        return expenses.post_confirm_expense("42", ExpenseConfirmRequest(expected_row_version=4),
            "original-confirm", auth, db).model_dump(mode="json")

    with confirmation_store() as db:
        original = db.get(Expense, 42)
        original.original_currency_code, original.original_amount_minor = currency, minor
        db.commit()
        first = submit(db)
        receipt = first["confirmation_receipt"]
        assert (receipt["merchant"], receipt["amount_cents"], receipt["original_currency_code"],
            receipt["original_amount_minor"], receipt["row_version"]) == ("首次便利店", 12860, currency, minor, 5)
        assert first["image_deleted_at"] is not None and first["thumbnail_deleted_at"] is not None
        assert "image_deleted_at" not in receipt
    with confirmation_store() as db:
        later = db.get(Expense, 42)
        later.merchant, later.amount_cents, later.row_version, later.fact_revision = "后来人工更正", 9900, 9, 2
        db.commit()
    with confirmation_store() as db:
        replay = submit(db)
        assert replay["confirmation_receipt"] == receipt
        assert (replay["merchant"], replay["amount_cents"], replay["row_version"]) == ("后来人工更正", 9900, 9)
        assert replay["image_deleted_at"] == first["image_deleted_at"]


@pytest.mark.parametrize("receipt", [None, {}, {"id": 999, "status": "confirmed"}])
def test_old_or_invalid_confirmation_receipt_requires_review_instead_of_current_fallback(confirmation_store, receipt):
    with confirmation_store() as db:
        _confirm(db)
        db.scalar(select(ApiIdempotencyKey)).response_body = receipt
        db.commit()
    with confirmation_store() as db:
        with pytest.raises(AppError) as rejected:
            _confirm(db)
        assert rejected.value.error == "expense_confirmation_original_requires_review"
        assert db.get(Expense, 42).row_version == 5
