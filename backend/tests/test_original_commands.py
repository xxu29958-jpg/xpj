"""Same-bill attachment commands retain real bytes, identity and accepted results."""

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
        amount_minor=1234, accounting_date="2026-08-30", fact_revision=3,
        attachment_cleanup_request=None, image_replenished_at=None)
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


@pytest.fixture
def replenishment_case(verification_case, monkeypatch):
    from tests._infra.assets import PNG_BYTES

    case = verification_case
    case.data = PNG_BYTES
    case.expense.image_hash = hashlib.sha256(PNG_BYTES).hexdigest()
    case.path.write_bytes(b"damaged original")
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(
        upload_dir=case.path.parents[1], max_upload_size_bytes=1024 * 1024))
    return case


def _replenish(case, *, data=None, version=4, expected=None):
    from app.schemas._original_attachment import OriginalReplenishmentRequest

    return case.commands.replenish_original(case.db, expense_id=7, auth=case.auth,
        payload=OriginalReplenishmentRequest(expected_row_version=version,
            expected_sha256=expected or hashlib.sha256(case.data).hexdigest()),
        data=case.data if data is None else data, filename="receipt.png", content_type="image/png",
        idempotency_key="replenishment-1")


def test_replenishment_preserves_bill_history_and_available_thumbnail(replenishment_case):
    case = replenishment_case
    previous = vars(case.expense).copy()
    receipt = _replenish(case)
    path = file_service.resolve_upload_path_for_tenant(case.expense.image_path, "owner")
    assert path != case.path and path.read_bytes() == case.data
    assert case.path.read_bytes() == b"damaged original"  # No destructive overwrite.
    for name in ("id", "public_id", "amount_minor", "accounting_date", "fact_revision", "thumbnail_path"):
        assert getattr(case.expense, name) == previous[name]
    assert case.expense.image_replenished_at.tzinfo is not None
    assert (receipt.operation, receipt.row_version, receipt.sha256) == ("replenish_original", 5, previous["image_hash"])
    case.db.commit.assert_called_once_with()


def test_intact_original_cannot_be_replenished_to_renew_retention(replenishment_case):
    case = replenishment_case
    case.path.write_bytes(case.data)
    old_path = case.expense.image_path
    with pytest.raises(AppError) as rejected:
        _replenish(case)
    assert rejected.value.error == "original_replenishment_not_needed"
    assert case.expense.image_path == old_path
    assert case.expense.image_replenished_at is None
    assert list(case.path.parent.iterdir()) == [case.path]
    case.db.commit.assert_not_called()


def test_replenishment_detaches_thumbnail_owned_by_old_cleanup(replenishment_case):
    from uuid import uuid4

    from app.attachment_cleanup_contract import CleanupFile, CleanupRequest

    case = replenishment_case
    request = CleanupRequest(request_id=uuid4(), reason="after_confirm", requested_at=datetime.now(UTC),
        image=CleanupFile(reference=case.expense.image_path), thumbnail=CleanupFile(reference=case.expense.thumbnail_path))
    case.expense.attachment_cleanup_request = request.model_dump(mode="json")
    case.path.write_bytes(case.data)  # A pending cleanup of this original still permits recovery.
    _replenish(case)
    assert case.expense.attachment_cleanup_request == request.model_dump(mode="json")
    assert case.expense.thumbnail_path is None
    assert case.expense.thumbnail_deleted_at is None
    assert case.expense.image_path != request.image.reference


def test_replenishment_allows_new_thumbnail_after_completed_cleanup(replenishment_case):
    case = replenishment_case
    case.expense.image_deleted_at = case.expense.thumbnail_deleted_at = datetime.now(UTC)
    _replenish(case)
    assert case.expense.image_deleted_at is None
    assert case.expense.thumbnail_deleted_at is None
    assert case.expense.thumbnail_path is None


@pytest.mark.parametrize("kind", ["stale_version", "different_identity", "unverified_identity", "different_bytes"])
def test_replenishment_rejections_do_not_save_or_rebind(replenishment_case, kind):
    case = replenishment_case
    before_reference = case.expense.image_path
    if kind == "unverified_identity":
        case.expense.image_hash = "legacy"
    kwargs = {"version": 3} if kind == "stale_version" else {}
    if kind == "different_identity":
        kwargs["expected"] = "a" * 64
    if kind == "different_bytes":
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (2, 2), (255, 0, 0)).save(buffer, "PNG")
        kwargs["data"] = buffer.getvalue()
    before_files = list(case.path.parents[1].rglob("*"))
    with pytest.raises(AppError):
        _replenish(case, **kwargs)
    assert case.expense.image_path == before_reference
    assert list(case.path.parents[1].rglob("*")) == before_files
    case.db.commit.assert_not_called()


def test_lost_commit_ack_keeps_new_original_and_same_key_replays_receipt(replenishment_case):
    case = replenishment_case
    case.db.commit.side_effect = RuntimeError("synthetic commit acknowledgement loss")
    with pytest.raises(RuntimeError):
        _replenish(case)
    path = file_service.resolve_upload_path_for_tenant(case.expense.image_path, "owner")
    assert path.read_bytes() == case.data
    accepted = case.accepted.call_args.kwargs["response_body"]
    case.record.response_body = accepted
    case.claim.return_value.kind = IdempotencyOutcomeKind.HIT
    case.db.commit.reset_mock()
    original_files = list(case.path.parents[1].rglob("*"))
    assert _replenish(case).model_dump(mode="json") == accepted
    assert list(case.path.parents[1].rglob("*")) == original_files
    case.db.commit.assert_not_called()


def test_precommit_failure_discards_only_new_unpublished_file(replenishment_case):
    case = replenishment_case
    case.accepted.side_effect = RuntimeError("synthetic receipt staging failure")
    with pytest.raises(RuntimeError):
        _replenish(case)
    assert case.path.read_bytes() == b"damaged original"
    remaining = [path for path in case.path.parents[1].rglob("*") if path.is_file()]
    assert remaining == [case.path]
    case.db.commit.assert_not_called()


@pytest.fixture
def cleanup_command_case(verification_case, monkeypatch):
    from uuid import uuid4

    from app.attachment_cleanup_contract import CleanupFile, CleanupRequest
    from app.services import attachment_cleanup_service

    case = verification_case
    case.request = CleanupRequest(request_id=uuid4(), reason="after_confirm", requested_at=datetime.now(UTC),
        image=CleanupFile(reference=case.expense.image_path), thumbnail=CleanupFile(reference=case.expense.thumbnail_path))
    case.expense.attachment_cleanup_request = case.request.model_dump(mode="json")
    case.thumbnail = case.path.with_name("receipt.thumb.webp")
    case.thumbnail.write_bytes(b"derived thumbnail")
    case.settings = SimpleNamespace(delete_image_after_confirm=True, delete_image_after_days=1, delete_rejected_after_days=1)
    monkeypatch.setattr(attachment_cleanup_service, "get_settings", lambda: case.settings)
    monkeypatch.setattr(attachment_cleanup_service, "authorize_currency_metadata_write", lambda _db: None)
    return case


def _continue_cleanup(case, *, cancel=False, request_id=None):
    from app.schemas._original_attachment import OriginalCleanupRequest

    return case.commands.continue_original_cleanup(case.db, expense_id=7, auth=case.auth,
        payload=OriginalCleanupRequest(expected_row_version=4, request_id=request_id or case.request.request_id),
        cancel_remaining=cancel, idempotency_key="cleanup-1")


def test_explicit_retry_continues_one_accepted_cleanup(cleanup_command_case):
    case = cleanup_command_case
    receipt = _continue_cleanup(case)
    assert not case.path.exists() and not case.thumbnail.exists()
    assert case.expense.attachment_cleanup_request is None
    assert case.expense.fact_revision == 3
    assert (receipt.operation, receipt.cleanup_request_id, receipt.cleanup_pending) == (
        "retry_original_cleanup", case.request.request_id, False)
    case.db.commit.assert_called_once_with()


def test_explicit_cancel_preserves_unexecuted_files(cleanup_command_case):
    case = cleanup_command_case
    receipt = _continue_cleanup(case, cancel=True)
    assert case.path.read_bytes() == BYTES
    assert case.thumbnail.read_bytes() == b"derived thumbnail"
    assert case.expense.image_deleted_at is None
    assert case.expense.thumbnail_deleted_at is None
    assert case.expense.attachment_cleanup_request is None
    assert receipt.cleanup_pending is False
    assert receipt.operation == "cancel_original_cleanup"


def test_cleanup_retry_does_not_override_disabled_policy(cleanup_command_case):
    case = cleanup_command_case
    case.settings.delete_image_after_confirm = False
    receipt = _continue_cleanup(case)
    assert case.path.read_bytes() == BYTES
    assert case.expense.attachment_cleanup_request == case.request.model_dump(mode="json")
    assert receipt.cleanup_pending is True


def test_old_cleanup_command_cannot_consume_a_new_request(cleanup_command_case):
    from uuid import uuid4

    case = cleanup_command_case
    with pytest.raises(AppError) as rejected:
        _continue_cleanup(case, request_id=uuid4())
    assert rejected.value.error == "attachment_cleanup_changed"
    assert case.path.read_bytes() == BYTES
    case.db.commit.assert_not_called()


def test_cleanup_accepted_key_survives_request_settlement(cleanup_command_case):
    case = cleanup_command_case
    accepted = _continue_cleanup(case)
    case.claim.return_value.kind = IdempotencyOutcomeKind.HIT
    case.record.response_body = accepted.model_dump(mode="json")
    case.db.commit.reset_mock()
    assert _continue_cleanup(case) == accepted
    case.db.commit.assert_not_called()
