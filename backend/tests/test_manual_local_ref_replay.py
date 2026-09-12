"""Legacy operation ACK recovery must not require a newer creation receipt."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes import expenses
from app.schemas import ExpenseConfirmRequest, ExpenseRejectRequest, ExpenseUpdateRequest
from app.services import expense_edit_command_service as edit
from app.services import expense_query, expense_review_command_service, idempotency
from app.services.expense_service import _update


@pytest.mark.parametrize("operation", ["patch", "confirm", "reject"])
def test_accepted_local_operation_replays_when_legacy_creation_receipt_is_missing(monkeypatch, operation):
    db = Mock(spec=Session)
    auth = SimpleNamespace(tenant_id="owner", account_id=1, device_id=7)
    expense = SimpleNamespace(id=42, row_version=3, source="手动记账", status="pending")
    state = SimpleNamespace(claim=None, creation=SimpleNamespace(id=42, row_version=3), writes=0, claim_calls=0)
    prepare_fx = Mock(return_value=None)
    monkeypatch.setattr(edit, "prepare_pending_expense_fx", prepare_fx)
    monkeypatch.setattr(expense_query, "resolve_expense", lambda *_a, **_k: expense)
    monkeypatch.setattr(expense_query, "read_manual_creation_receipt", lambda *_a, **_k: state.creation)
    def claim(_db, **fields):
        state.claim_calls += 1
        if state.claim is None:
            state.claim = SimpleNamespace(**fields, status="in_progress")
            kind = idempotency.IdempotencyOutcomeKind.PROCEED
        else:
            assert state.claim.status == "succeeded"
            assert state.claim.idempotency_key == fields["idempotency_key"] == "original-operation"
            assert state.claim.request_fingerprint == fields["request_fingerprint"]
            kind = idempotency.IdempotencyOutcomeKind.HIT
        return SimpleNamespace(kind=kind, row=state.claim)
    monkeypatch.setattr(idempotency, "claim_idempotency_key", claim)
    def write(*_a, **_k):
        state.writes += 1
        expense.row_version, expense.status = 4, "rejected" if operation == "reject" else "confirmed"
        return expense
    owner = {"patch": edit, "confirm": expense_review_command_service, "reject": expenses}[operation]
    writer = {"patch": "update_expense", "confirm": "confirm_expense", "reject": "reject_expense"}[operation]
    monkeypatch.setattr(owner, writer, write)
    monkeypatch.setattr(owner, "get_expense", lambda *_a, **_k: expense)
    monkeypatch.setattr(expense_review_command_service, "cleanup_after_confirm", lambda *_a: False)
    monkeypatch.setattr(expenses, "expense_to_response", lambda _db, *, expense, tenant_id: expense)
    route, payload = {
        "patch": (expenses.patch_expense, ExpenseUpdateRequest(expected_row_version=0, note="Original edit")),
        "confirm": (expenses.post_confirm_expense, ExpenseConfirmRequest(expected_row_version=0)),
        "reject": (expenses.post_reject_expense, ExpenseRejectRequest(expected_row_version=0)),
    }[operation]
    assert route("local:original", payload, "original-operation", auth, db) is expense
    assert state.writes == 1
    state.creation = None
    assert route("local:original", payload, "original-operation", auth, db) is expense
    assert state.writes == 1 and state.claim_calls == 2
    assert db.commit.call_count == 1
    if operation == "patch":
        prepare_fx.assert_called_once_with(db, expense=expense,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id)
    else:
        prepare_fx.assert_not_called()


@pytest.mark.parametrize(("operation", "status"), [("confirm", "confirmed"), ("reject", "rejected")])
def test_fresh_zero_cannot_accept_a_terminal_state_without_original_operation_receipt(monkeypatch, operation, status):
    db = Mock(spec=Session)
    auth = SimpleNamespace(tenant_id="owner", account_id=1, device_id=7)
    expense = SimpleNamespace(id=42, row_version=8, source="手动记账", status=status)
    monkeypatch.setattr(expense_query, "resolve_expense", lambda *_a, **_k: expense)
    monkeypatch.setattr(expense_query, "read_manual_creation_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(_update, "resolve_write_capability", lambda _db: None)
    monkeypatch.setattr(_update, "get_expense", lambda *_a: expense)
    write = Mock(return_value=0)
    monkeypatch.setattr(_update, "claim_row_with_token", write)
    claim = SimpleNamespace(target_type="expense", target_id="42")
    owner = expense_review_command_service if operation == "confirm" else expenses
    monkeypatch.setattr(owner, "claim_idempotent_request", lambda *_a, **_k: claim)
    accepted = Mock()
    monkeypatch.setattr(owner, "mark_idempotency_succeeded", accepted)
    cleanup = Mock(return_value=False)
    monkeypatch.setattr(expense_review_command_service, "cleanup_after_confirm", cleanup)
    monkeypatch.setattr(expenses, "expense_to_response", lambda _db, *, expense, tenant_id: expense)
    route = expenses.post_confirm_expense if operation == "confirm" else expenses.post_reject_expense
    payload = ExpenseConfirmRequest(expected_row_version=0) if operation == "confirm" else ExpenseRejectRequest(expected_row_version=0)
    with pytest.raises(AppError) as caught:
        route("local:legacy", payload, "fresh-operation", auth, db)
    assert (caught.value.error, caught.value.status_code) == ("state_conflict", 409)
    accepted.assert_not_called()
    write.assert_not_called()
    cleanup.assert_not_called()
    db.commit.assert_not_called()
