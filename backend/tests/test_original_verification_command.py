"""Explicit verification binds a real reviewed file to one accepted command."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.schemas._original_attachment import OriginalVerificationRequest
from app.services import file_service
from app.services.idempotency import IdempotencyOutcomeKind
from app.tenants import AuthContext

BYTES = b"the original a person reviewed"


@pytest.fixture
def verification_case(monkeypatch, tmp_path):
    from app.services import original_command_service as commands

    path = tmp_path / "uploads" / "owner" / "receipt.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(BYTES)
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=path.parents[1]))
    expense = SimpleNamespace(id=7, public_id="bill-seven", tenant_id="owner", row_version=4,
        image_path="uploads/owner/receipt.png", image_hash="legacy", image_deleted_at=None,
        thumbnail_path="uploads/owner/receipt.thumb.webp", thumbnail_deleted_at=None,
        amount_minor=1234, accounting_date="2026-08-30", fact_revision=3)
    auth = AuthContext(11, "account-eleven", "Owner", "owner", "Home", 12, "device-twelve", "Phone", "owner", "app")
    db = Mock()
    record = SimpleNamespace(id=8, response_body=None)
    claim = Mock(return_value=SimpleNamespace(kind=IdempotencyOutcomeKind.PROCEED, row=record))
    monkeypatch.setattr(commands, "claim_idempotency_key", claim)
    monkeypatch.setattr(commands, "get_expense", Mock(return_value=expense))
    lock = Mock(return_value=auth)
    monkeypatch.setattr(commands, "lock_and_revalidate_mutation_actor", lock)
    currency = Mock()
    monkeypatch.setattr(commands, "authorize_currency_metadata_write", currency)

    def cas(*_args, **kwargs):
        if kwargs["expected_row_version"] != expense.row_version:
            return 0
        expense.row_version += 1
        return 1

    monkeypatch.setattr(commands, "claim_row_with_token", Mock(side_effect=cas))
    accepted = Mock()
    monkeypatch.setattr(commands, "mark_idempotency_succeeded", accepted)
    return SimpleNamespace(commands=commands, db=db, expense=expense, auth=auth, path=path,
        claim=claim, record=record, lock=lock, currency=currency, accepted=accepted)


def _verify(case, *, digest=None, version=4):
    return case.commands.verify_original(case.db, expense_id=7, auth=case.auth,
        payload=OriginalVerificationRequest(expected_row_version=version,
            reviewed_sha256=digest or hashlib.sha256(BYTES).hexdigest()), idempotency_key="verification-1")


def test_verification_adopts_only_reviewed_bytes_with_actor_audit(verification_case):
    case = verification_case
    receipt = _verify(case)
    assert case.expense.image_hash == hashlib.sha256(BYTES).hexdigest()
    assert (case.expense.id, case.expense.amount_minor, case.expense.accounting_date, case.expense.fact_revision) == (
        7, 1234, "2026-08-30", 3)
    assert case.expense.thumbnail_path == "uploads/owner/receipt.thumb.webp"
    assert case.path.read_bytes() == BYTES
    audit = case.db.add.call_args.args[0]
    assert (audit.action, audit.actor_account_id, audit.resource_public_id) == ("original_verified", 11, "bill-seven")
    assert json.loads(audit.detail) == {"sha256": case.expense.image_hash, "basis": "current_review"}
    assert (receipt.operation, receipt.expense_id, receipt.public_id, receipt.row_version) == (
        "verify_original", 7, "bill-seven", 5)
    assert receipt.sha256 == case.expense.image_hash
    case.db.commit.assert_called_once_with()
    assert case.accepted.call_args.kwargs["response_body"] == receipt.model_dump(mode="json")


def test_changed_since_review_refuses_new_baseline(verification_case):
    case = verification_case
    case.path.write_bytes(b"changed after review")
    with pytest.raises(AppError) as rejected:
        _verify(case)
    assert rejected.value.error == "original_review_conflict"
    assert case.expense.image_hash == "legacy"
    assert case.path.read_bytes() == b"changed after review"
    case.db.commit.assert_not_called()
    case.accepted.assert_not_called()
    case.db.rollback.assert_called_once_with()


def test_known_identity_cannot_be_rebased_by_verification(verification_case):
    case = verification_case
    case.expense.image_hash = hashlib.sha256(b"an earlier original").hexdigest()
    with pytest.raises(AppError) as rejected:
        _verify(case)
    assert rejected.value.error == "original_already_verified"
    assert case.expense.image_hash == hashlib.sha256(b"an earlier original").hexdigest()
    case.db.commit.assert_not_called()


def test_stale_bill_version_preserves_current_attachment(verification_case):
    case = verification_case
    with pytest.raises(AppError) as rejected:
        _verify(case, version=3)
    assert rejected.value.error == "state_conflict"
    assert case.expense.image_hash == "legacy"
    case.db.commit.assert_not_called()


@pytest.mark.parametrize("state", ["missing", "cleaned"])
def test_unavailable_original_cannot_acquire_a_digest(verification_case, state):
    case = verification_case
    if state == "cleaned":
        case.expense.image_deleted_at = datetime(2026, 9, 20, tzinfo=UTC)
    case.path.unlink()
    with pytest.raises(AppError) as rejected:
        _verify(case)
    assert rejected.value.error == "image_not_found"
    assert case.expense.image_hash == "legacy"
    case.db.commit.assert_not_called()


def test_accepted_key_returns_original_receipt_before_new_checks(verification_case):
    case = verification_case
    accepted = _verify(case)
    case.record.response_body = accepted.model_dump(mode="json")
    case.claim.return_value.kind = IdempotencyOutcomeKind.HIT
    case.path.unlink()
    case.commands.claim_row_with_token.reset_mock()
    case.currency.reset_mock()
    case.db.commit.reset_mock()
    replayed = _verify(case)
    assert replayed == accepted
    case.commands.claim_row_with_token.assert_not_called()
    case.currency.assert_not_called()
    case.db.commit.assert_not_called()
    assert case.lock.call_count == 2  # A historical receipt never bypasses current identity.


@pytest.mark.parametrize("role,scope", [("viewer", "app"), ("owner", "upload"), ("owner", "admin")])
def test_read_or_upload_credentials_cannot_verify_originals(verification_case, role, scope):
    from dataclasses import replace

    case = verification_case
    case.auth = replace(case.auth, role=role, scope=scope)
    with pytest.raises(AppError) as rejected:
        _verify(case)
    assert rejected.value.status_code == 403
    case.claim.assert_not_called()
    case.db.commit.assert_not_called()


def test_commit_failure_keeps_source_and_never_reports_accepted(verification_case):
    case = verification_case
    case.db.commit.side_effect = RuntimeError("synthetic commit outcome unavailable")
    with pytest.raises(RuntimeError):
        _verify(case)
    assert case.path.read_bytes() == BYTES
    case.db.rollback.assert_called_once_with()
