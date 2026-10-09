"""Original subtask receipts cannot lend a peer's OCC token to offline work.

The actual routes, domain writers, CAS, receipt rows and transactions run on
SQLite; admission/authentication are controlled. Existing API tests own PG.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Account, ApiIdempotencyKey, Expense, ExpenseItem, ExpenseSplit, LedgerAuditLog, LedgerMember
from app.routes import expenses
from app.schemas import ExpenseAcknowledgeItemsMismatchRequest, ExpenseItemReplaceRequest, ExpenseSplitReplaceRequest
from app.services import expense_split_service, receipt_item_service
from tests.test_expense_confirmation_receipt import confirmation_store  # noqa: F401


@pytest.fixture
def subtask_store(confirmation_store, monkeypatch):  # noqa: F811 - shared pytest fixture
    metadata = MetaData()
    for model in (Account, LedgerMember, ExpenseItem, ExpenseSplit, LedgerAuditLog):
        Table(model.__tablename__, metadata, *(Column(column.name,
            JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
    metadata.create_all(confirmation_store)
    with Session(confirmation_store) as db:
        db.add(Account(id=11, display_name="自己"))
        db.add(LedgerMember(id=1, ledger_id="owner", account_id=11, role="owner"))
        db.commit()
    for module in (receipt_item_service, expense_split_service):
        monkeypatch.setattr(module, "resolve_write_capability", lambda *args: None)
    return confirmation_store


def _submit(db, kind, version, key, *, label="原输入", amount=500):
    auth = SimpleNamespace(tenant_id="owner", device_id=None, account_id=11)
    if kind == "items":
        route = expenses.put_expense_item_rows
        payload = ExpenseItemReplaceRequest(expected_row_version=version,
            items=[{"name": label, "amount_cents": amount, "category": "购物"}])
    elif kind == "splits":
        route = expenses.put_expense_split_rows
        payload = ExpenseSplitReplaceRequest(expected_row_version=version,
            splits=[{"member_id": 1, "amount_cents": amount, "note": label}])
    else:
        route = expenses.acknowledge_expense_items_mismatch
        payload = ExpenseAcknowledgeItemsMismatchRequest(expected_row_version=version)
    return route("42", payload, idempotency_key=key, auth=auth, db=db)


def _prepare(db, kind):
    if kind == "ack":
        return _submit(db, "items", 4, "seed-mismatch").row_version
    return 4


def _facts(db):
    expense = db.get(Expense, 42)
    return (expense.status, expense.row_version, expense.amount_cents, expense.items_sum_status,
        [(row.name, row.amount_cents) for row in db.scalars(select(ExpenseItem))],
        [(row.member_id, row.amount_cents, row.note) for row in db.scalars(select(ExpenseSplit))],
        [(row.action, row.actor_account_id) for row in db.scalars(select(LedgerAuditLog))])


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_replay_preserves_first_receipt_and_next_intent_conflicts_with_peer(subtask_store, kind):
    with Session(subtask_store) as db:
        original_version = _prepare(db, kind)
        first = _submit(db, kind, original_version, "original-key").model_dump(mode="json")
    with Session(subtask_store) as db:
        _submit(db, "splits" if kind == "splits" else "items", first["row_version"], "peer-key",
            label="他端后来填写", amount=700)
        peer_facts = _facts(db)
    with Session(subtask_store) as db:
        replay = _submit(db, kind, original_version, "original-key").model_dump(mode="json")
        # This is the next token actually consumed by Android's outbox cascade.
        with pytest.raises(AppError) as conflict:
            _submit(db, "splits" if kind == "splits" else "items", replay["row_version"], "following-key",
                label="后续离线原稿", amount=900)
        assert conflict.value.error == "state_conflict"
        db.rollback()
        assert replay == first
        assert _facts(db) == peer_facts
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == "original-key")).response_body == first


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_accepted_subtask_without_original_receipt_requires_review(subtask_store, kind):
    with Session(subtask_store) as db:
        original_version = _prepare(db, kind)
        _submit(db, kind, original_version, "original-key")
        before = _facts(db)
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "original-key"))
        claim.response_body = None
        db.commit()
    with Session(subtask_store) as db:
        with pytest.raises(AppError) as refusal:
            _submit(db, kind, original_version, "original-key")
        assert refusal.value.error == "expense_subtask_original_requires_review"
        assert _facts(db) == before


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_subtask_and_first_receipt_roll_back_together(subtask_store, kind, monkeypatch):
    with Session(subtask_store) as db:
        original_version = _prepare(db, kind)
        before = _facts(db)
    from app.services import expense_subtask_command_service as owner

    def fail(*args, **kwargs):
        raise SQLAlchemyError("injected receipt failure")

    monkeypatch.setattr(owner, "mark_idempotency_succeeded", fail)
    with Session(subtask_store) as db, pytest.raises(SQLAlchemyError, match="injected receipt failure"):
        _submit(db, kind, original_version, "original-key")
    with Session(subtask_store) as db:
        assert _facts(db) == before
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == "original-key")) is None
