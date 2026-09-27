"""Shared OCR retry keeps the original intent, canonical replay and FX transaction."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes import expenses
from app.schemas import ExpenseOcrRetryRequest
from app.services import expense_ocr_command_service as command
from app.services import idempotency


def test_api_retry_preserves_original_token_and_current_canonical_replay_without_second_ocr(monkeypatch):
    db = Mock(spec=Session)
    auth = SimpleNamespace(tenant_id="owner", account_id=1, device_id=7)
    expense = SimpleNamespace(id=42, row_version=3, status="pending", amount_cents=1200)
    accepted_claim = SimpleNamespace(status="in_progress")
    fingerprints = []

    def claim(_db, **fields):
        assert fields["operation"] == "retry_ocr" and fields["target_id"] == "42"
        assert fields["tenant_id"] == "owner" and fields["idempotency_key"] == "original-key"
        fingerprints.append(fields["request_fingerprint"])
        return SimpleNamespace(row=accepted_claim, kind=idempotency.IdempotencyOutcomeKind.HIT
            if accepted_claim.status == "succeeded" else idempotency.IdempotencyOutcomeKind.PROCEED)

    monkeypatch.setattr(idempotency, "claim_idempotency_key", claim)
    monkeypatch.setattr(expenses, "resolve_expense_for_mutation", Mock(return_value=(42, 3)))
    monkeypatch.setattr(expenses, "expense_to_response", lambda _db, *, tenant_id, expense: expense)
    retry = Mock(return_value=expense)
    monkeypatch.setattr(command, "retry_expense_ocr", retry)
    monkeypatch.setattr(command, "get_expense", lambda *_args: expense)
    task = object()
    prepare = Mock(return_value=task)
    monkeypatch.setattr(command, "prepare_pending_expense_fx", prepare)

    def mark(_db, row, **fields):
        assert fields == {"resource_type": "expense", "resource_id": "42"}
        row.status = "succeeded"
    monkeypatch.setattr(command, "mark_idempotency_succeeded", mark)

    def submit(_db, submitted):
        assert submitted is task and db.commit.call_count == 1 and accepted_claim.status == "succeeded"
    submit_fx = Mock(side_effect=submit)
    monkeypatch.setattr(command, "submit_pending_expense_fx", submit_fx)
    payload = ExpenseOcrRetryRequest(expected_row_version=0)
    assert expenses.post_retry_ocr("local:original", payload, "original-key", auth, db) is expense
    retry.assert_called_once_with(db, 42, "owner", expected_row_version=3, commit=False)
    prepare.assert_called_once_with(db, expense=expense, initiator_account_id=1, initiator_device_id=7)
    db.refresh.assert_called_once_with(expense)

    # A later user confirmation is canonical; the original key must not OCR it again.
    expense.row_version, expense.status, expense.amount_cents = 9, "confirmed", 9900
    assert expenses.post_retry_ocr("local:original", payload, "original-key", auth, db) is expense
    assert (expense.row_version, expense.status, expense.amount_cents) == (9, "confirmed", 9900)
    expected = idempotency.fingerprint_request(operation="retry_ocr", target_id="42", body={}, expected_row_version=0)
    assert fingerprints == [expected, expected]
    assert retry.call_count == submit_fx.call_count == db.commit.call_count == 1
    db.rollback.assert_not_called()


@pytest.mark.parametrize("stage", ["ocr", "fx"])
def test_retry_failure_rolls_back_claim_and_never_publishes_success_or_fx(monkeypatch, stage):
    db = Mock(spec=Session)
    expense = SimpleNamespace(id=42, status="pending")
    monkeypatch.setattr(command, "claim_idempotent_request", Mock(return_value=object()))
    failure = AppError("state_conflict", status_code=409) if stage == "ocr" else SQLAlchemyError("FX staging failed")
    monkeypatch.setattr(command, "retry_expense_ocr", Mock(side_effect=failure) if stage == "ocr" else Mock(return_value=expense))
    monkeypatch.setattr(command, "prepare_pending_expense_fx", Mock(side_effect=failure) if stage == "fx" else Mock())
    succeeded, submit = Mock(), Mock()
    monkeypatch.setattr(command, "mark_idempotency_succeeded", succeeded)
    monkeypatch.setattr(command, "submit_pending_expense_fx", submit)
    with pytest.raises(type(failure)) as caught:
        command.submit_expense_ocr_retry(db, expense_id=42, tenant_id="owner", initiator_account_id=1,
            initiator_device_id=None, expected_row_version=3, request_expected_row_version=0, idempotency_key="original-key")
    assert caught.value is failure
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()
    succeeded.assert_not_called()
    submit.assert_not_called()
