"""An accepted confirmation keeps its first result across later financial edits.

SQLite exercises the actual idempotency rows and commit boundary here. The
financial transition is controlled; PostgreSQL qualification owns its fences.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense
from app.schemas import ExpenseConfirmRequest, ExpenseResponse
from app.services import expense_review_command_service as owner


@pytest.fixture
def confirmation_store(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'confirmation.sqlite'}")

    @event.listens_for(engine, "connect")
    def explicit_transactions(connection, record):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    ApiIdempotencyKey.__table__.create(engine)
    metadata = MetaData()
    Table(Expense.__tablename__, metadata, *(Column(column.name,
        JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
        for column in Expense.__table__.columns))
    metadata.create_all(engine)
    now = datetime(2026, 10, 8, tzinfo=UTC)
    with Session(engine) as db:
        db.add(Expense(id=42, public_id="original-expense", tenant_id="owner", merchant="首次便利店", category="购物",
            home_currency_code="CNY", original_currency_code="JPY", original_amount_minor=2850, amount_cents=12860,
            source="上传", status="pending", fx_status="ready", duplicate_status="none", row_version=4,
            fact_revision=0, created_at=now, updated_at=now, expense_time=now))
        db.commit()

    def confirm(db, expense_id, tenant_id, **kwargs):
        row = db.get(Expense, expense_id)
        assert row.tenant_id == tenant_id and row.status == "pending"
        assert row.row_version == kwargs["expected_row_version"]
        row.status = "confirmed"
        row.row_version += 1
        row.fact_revision += 1
        row.confirmed_at = now
        db.flush()
        return row

    monkeypatch.setattr(owner, "confirm_expense", confirm)
    monkeypatch.setattr(owner, "cleanup_after_confirm", lambda *args: None)
    monkeypatch.setattr(owner, "expense_to_response", lambda db, *, expense, tenant_id: ExpenseResponse.model_validate(expense))
    yield engine
    engine.dispose()


def _confirm(db, **changes):
    return owner.confirm_expense_submission(db, expense_id=42, tenant_id="owner", expected_row_version=4,
        request_expected_row_version=4, idempotency_key="original-confirm", intent_body={}, update_payload=None,
        require_idempotency=True, **changes)


def test_confirmation_replay_returns_first_amount_and_merchant_after_later_correction(confirmation_store):
    with Session(confirmation_store) as db:
        original = ExpenseResponse.model_validate(_confirm(db)).model_dump(mode="json")
        assert (original["merchant"], original["amount_cents"], original["row_version"]) == ("首次便利店", 12860, 5)
    with Session(confirmation_store) as db:
        later = db.get(Expense, 42)
        later.merchant, later.amount_cents, later.row_version, later.fact_revision = "后来人工更正", 9900, 9, 2
        db.commit()
    with Session(confirmation_store) as db:
        replay = ExpenseResponse.model_validate(_confirm(db)).model_dump(mode="json")
        assert replay == original
        current = db.get(Expense, 42)
        assert (current.merchant, current.amount_cents, current.row_version) == ("后来人工更正", 9900, 9)
        assert db.scalar(select(ApiIdempotencyKey)).response_body == original


def test_confirmation_and_receipt_roll_back_together(confirmation_store, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError("injected receipt failure")

    monkeypatch.setattr(owner, "mark_idempotency_succeeded", fail)
    with Session(confirmation_store) as db, pytest.raises(SQLAlchemyError, match="injected receipt failure"):
        _confirm(db)
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.status, current.row_version, current.fact_revision) == ("pending", 4, 0)
        assert db.scalar(select(ApiIdempotencyKey)) is None


def test_web_original_confirmation_precedes_validation_against_a_later_manual_fx_fact(confirmation_store, monkeypatch):
    from app.routes._web_expense_confirm_command import confirm_web_expense
    from app.routes._web_expense_edit_form import WebExpenseEditForm
    from app.routes._web_expense_return_context import ExpenseReturnContext

    monkeypatch.setattr(owner, "update_expense", lambda db, expense_id, *args, **kwargs: db.get(Expense, expense_id))
    form = WebExpenseEditForm(ledger_id="owner", expected_row_version="4", idempotency_key="web-confirm-original",
        save_before_confirm=True, amount_yuan="2850", original_currency="JPY", manual_exchange_rate="0.045123",
        merchant="首次便利店", category="购物", note="", tags="", expense_time=None, fragment=0,
        return_context=ExpenseReturnContext(return_to="pending", return_filter="ready", return_page="2"))
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        current.exchange_rate_source, current.exchange_rate_to_cny = "manual", Decimal("0.045123")
        db.commit()
        first = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=form)
        assert first.error is None
        assert first.receipt.amount_cents == 12860
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        current.exchange_rate_to_cny, current.original_amount_minor = Decimal("0.08"), 4000
        current.amount_cents, current.merchant, current.row_version = 32000, "后来人工更正", 9
        db.commit()
    with Session(confirmation_store) as db:
        replay = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=form)
        assert replay.error is None, replay.error
        assert replay.receipt.model_dump(mode="json") == first.receipt.model_dump(mode="json")
        changed = confirm_web_expense(db, expense_id=42, selected_ledger_id="owner", form=replace(form, amount_yuan="9999"))
        assert changed.error_status == 422 and changed.error_code == "idempotency_key_reused"
        current = db.get(Expense, 42)
        assert (current.amount_cents, current.merchant, current.row_version) == (32000, "后来人工更正", 9)


def test_web_original_save_is_accepted_after_later_currency_and_status_changes(confirmation_store, monkeypatch):
    from app.routes._web_expense_edit_command import apply_web_expense_form
    from app.routes._web_expense_edit_form import WebExpenseEditForm
    from app.routes._web_expense_return_context import ExpenseReturnContext
    from app.services import expense_edit_command_service as edit_owner

    def update(db, expense_id, tenant_id, payload, **kwargs):
        current = db.get(Expense, expense_id)
        assert current.status == "pending" and current.row_version == payload.expected_row_version
        current.merchant, current.row_version = payload.merchant, current.row_version + 1
        db.flush()
        return current

    monkeypatch.setattr(edit_owner, "update_expense", update)
    monkeypatch.setattr(edit_owner, "prepare_pending_expense_fx", lambda *args, **kwargs: None)
    form = WebExpenseEditForm(ledger_id="owner", expected_row_version="4", idempotency_key="web-save-original",
        save_before_confirm=True, amount_yuan="2850", original_currency="JPY", manual_exchange_rate="",
        merchant="保存的商家", category="购物", note="", tags="", expense_time=None, fragment=0,
        return_context=ExpenseReturnContext(return_to="pending", return_filter="ready"))

    def submit(db, original=form):
        return apply_web_expense_form(db, expense_id=42, selected_ledger_id="owner",
            initiator_account_id=None, initiator_device_id=None, form=original)

    with Session(confirmation_store) as db:
        assert submit(db).error is None
        current = db.get(Expense, 42)
        assert (current.merchant, current.status, current.row_version) == ("保存的商家", "pending", 5)
        current.original_currency_code, current.original_amount_minor = "USD", 9900
        current.merchant, current.status, current.row_version = "后来确认的商家", "confirmed", 9
        db.commit()
    with Session(confirmation_store) as db:
        replay = submit(db)
        assert replay.error is None, replay.error
        changed = submit(db, replace(form, merchant="另一个意图"))
        assert changed.error_status == 422 and changed.error_code == "idempotency_key_reused"
        current = db.get(Expense, 42)
        assert (current.merchant, current.status, current.original_currency_code, current.row_version) == (
            "后来确认的商家", "confirmed", "USD", 9)


def test_api_keeps_original_financial_receipt_beside_current_fact_and_original_disposal(confirmation_store, monkeypatch):
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

    with Session(confirmation_store) as db:
        first = submit(db)
        receipt = first["confirmation_receipt"]
        assert (receipt["merchant"], receipt["amount_cents"], receipt["original_currency_code"],
            receipt["original_amount_minor"], receipt["row_version"]) == ("首次便利店", 12860, "JPY", 2850, 5)
        assert first["image_deleted_at"] is not None and first["thumbnail_deleted_at"] is not None
        assert "image_deleted_at" not in receipt
    with Session(confirmation_store) as db:
        later = db.get(Expense, 42)
        later.merchant, later.amount_cents, later.row_version, later.fact_revision = "后来人工更正", 9900, 9, 2
        db.commit()
    with Session(confirmation_store) as db:
        replay = submit(db)
        assert replay["confirmation_receipt"] == receipt
        assert (replay["merchant"], replay["amount_cents"], replay["row_version"]) == ("后来人工更正", 9900, 9)
        assert replay["image_deleted_at"] == first["image_deleted_at"]


@pytest.mark.parametrize("receipt", [None, {}, {"id": 999, "status": "confirmed"}])
def test_old_or_invalid_confirmation_receipt_requires_review_instead_of_current_fallback(confirmation_store, receipt):
    with Session(confirmation_store) as db:
        _confirm(db)
        db.scalar(select(ApiIdempotencyKey)).response_body = receipt
        db.commit()
    with Session(confirmation_store) as db:
        with pytest.raises(AppError) as rejected:
            _confirm(db)
        assert rejected.value.error == "expense_confirmation_original_requires_review"
        assert db.get(Expense, 42).row_version == 5
