"""Real files and explicit commit snapshots; no PostgreSQL fixtures are used."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.attachment_cleanup_contract import CleanupFile, CleanupRequest
from app.errors import AppError
from app.models import Expense
from app.services import attachment_cleanup_service as cleanup
from app.services import cleanup_service, file_service, thumb_service
from app.services.expense_service._thumbnail_publication import claim_staged_thumbnail, publish_claimed_thumbnail
from app.services.time_service import now_utc


@pytest.fixture
def cleanup_case(tmp_path, monkeypatch):
    directory = tmp_path / "uploads" / "owner"
    directory.mkdir(parents=True)
    original, thumbnail = directory / "original.png", directory / "thumbnail.png"
    original.write_bytes(b"original admitted bytes")
    thumbnail.write_bytes(b"derived thumbnail")
    settings = SimpleNamespace(upload_dir=directory.parent, delete_image_after_confirm=True,
                               delete_image_after_days=1, delete_rejected_after_days=1)
    for module in (cleanup, cleanup_service, file_service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(cleanup, "authorize_currency_metadata_write", lambda _db: None)
    old = now_utc() - timedelta(days=3)
    expense = Expense(id=42, public_id=str(uuid4()), tenant_id="owner", status="confirmed", row_version=7,
                      fact_revision=2, updated_at=old, confirmed_at=old,
                      image_path="uploads/owner/original.png", thumbnail_path="uploads/owner/thumbnail.png")
    fields = ("image_path", "thumbnail_path", "image_deleted_at", "thumbnail_deleted_at",
              "attachment_cleanup_request", "image_replenished_at", "row_version", "fact_revision", "updated_at")
    durable = {field: deepcopy(getattr(expense, field)) for field in fields}
    db = Mock(spec=Session)
    db.scalars.return_value = [expense]
    case = SimpleNamespace(expense=expense, db=db, durable=durable, settings=settings, original=original,
                           thumbnail=thumbnail, commits=0, reject_commit=None, lose_ack=None, before_commit=None)

    def commit():
        case.commits += 1
        if case.before_commit:
            case.before_commit(case.commits)
        if case.reject_commit == case.commits:
            raise SQLAlchemyError("commit rejected")
        if not isinstance(expense.row_version, int):
            expense.row_version = durable["row_version"] + 1
        durable.update({field: deepcopy(getattr(expense, field)) for field in fields})
        if case.lose_ack == case.commits:
            raise SQLAlchemyError("commit acknowledgement lost")

    def refresh(*_args, **_kwargs):
        for field, value in durable.items():
            setattr(expense, field, deepcopy(value))

    db.commit.side_effect = commit
    db.refresh.side_effect = refresh
    db.rollback.side_effect = refresh
    return case


def _run(case):
    return cleanup.execute_attachment_cleanup(case.db, case.expense, reason="after_confirm",
                                               settings_provider=lambda: case.settings)


def _accept_only(case):
    request = CleanupRequest(request_id=uuid4(), reason="after_confirm", requested_at=now_utc(),
                             image=CleanupFile(reference=case.expense.image_path),
                             thumbnail=CleanupFile(reference=case.expense.thumbnail_path))
    case.expense.attachment_cleanup_request = request.model_dump(mode="json")
    case.db.commit()
    return request


def test_files_are_present_when_request_is_first_committed(cleanup_case):
    case = cleanup_case
    observed = []

    def observe(number):
        if number == 1:
            observed.append((case.original.is_file(), case.thumbnail.is_file(),
                             cleanup.read_cleanup_request(case.expense) is not None,
                             case.expense.image_deleted_at, case.expense.thumbnail_deleted_at))

    case.before_commit = observe
    result = _run(case)
    assert observed == [(True, True, True, None, None)]
    assert (result.deleted_images, result.deleted_thumbnails, result.pending) == (1, 1, False)
    assert case.durable["attachment_cleanup_request"] is None
    assert case.durable["image_deleted_at"] is not None
    assert case.durable["thumbnail_deleted_at"] is not None
    assert case.expense.fact_revision == 2


@pytest.mark.parametrize("failure_phase", ["request_ack", "settlement_commit", "settlement_ack"])
def test_commit_uncertainty_retries_original_request_without_double_counting(cleanup_case, failure_phase):
    case = cleanup_case
    if failure_phase == "request_ack":
        case.lose_ack = 1
    elif failure_phase == "settlement_commit":
        case.reject_commit = 2
    else:
        case.lose_ack = 2
    with pytest.raises(SQLAlchemyError):
        _run(case)
    case.db.rollback()
    if failure_phase != "settlement_ack":
        assert case.durable["attachment_cleanup_request"] is not None
    assert case.original.exists() == (failure_phase == "request_ack")
    case.lose_ack = case.reject_commit = None
    result = _run(case)
    expected = 1 if failure_phase == "request_ack" else 0
    assert (result.deleted_images, result.deleted_thumbnails) == (expected, expected)
    assert case.durable["attachment_cleanup_request"] is None
    assert case.durable["image_deleted_at"] is not None
    assert case.durable["thumbnail_deleted_at"] is not None
    assert case.expense.fact_revision == 2


def test_unlink_failure_is_per_file_and_can_resume(cleanup_case, monkeypatch):
    case = cleanup_case
    unlink = Path.unlink

    def locked_thumbnail(path, *args, **kwargs):
        if path == case.thumbnail:
            raise PermissionError("locked")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as locked:
        locked.setattr(Path, "unlink", locked_thumbnail)
        first = _run(case)
    request = cleanup.read_cleanup_request(case.expense)
    assert first.deleted_images == 1 and first.deleted_thumbnails == 0 and first.pending
    assert request.image.outcome == "deleted"
    assert request.thumbnail.error_code == "unlink_failed"
    assert case.expense.image_deleted_at is not None and case.expense.thumbnail_deleted_at is None
    second = _run(case)
    assert second.deleted_images == 0 and second.deleted_thumbnails == 1 and not second.pending


def test_replenishment_new_paths_survive_the_frozen_old_request(cleanup_case):
    case = cleanup_case
    old = _accept_only(case)
    replacement = case.original.with_name("replenished-unique.png")
    replacement.write_bytes(case.original.read_bytes())
    case.expense.image_path = "uploads/owner/replenished-unique.png"
    case.expense.thumbnail_path = None
    case.expense.image_replenished_at = now_utc()
    case.db.commit()
    result = _run(case)
    assert result.deleted_images == 1 and result.deleted_thumbnails == 1
    assert replacement.is_file() and not case.original.exists()
    assert case.expense.image_deleted_at is None and case.expense.thumbnail_deleted_at is None
    assert case.expense.attachment_cleanup_request is None
    assert old.image.reference != case.expense.image_path


def test_policy_off_preserves_unexecuted_request_and_cancel_settles_only_missing(cleanup_case):
    case = cleanup_case
    request = _accept_only(case)
    case.original.unlink()  # Earlier accepted execution may have lost its final commit.
    case.settings.delete_image_after_confirm = False
    paused = _run(case)
    assert paused.deleted_images == paused.deleted_thumbnails == 0 and paused.pending
    assert case.thumbnail.is_file() and case.expense.image_deleted_at is not None
    case.db.refresh.reset_mock()
    case.db.commit.reset_mock()
    result = cleanup.settle_cleanup_request(case.db, case.expense, expected_request_id=request.request_id,
                                            cancel_remaining=True)
    assert result.changed and not result.pending
    assert result.deleted_images == result.deleted_thumbnails == 0
    assert case.thumbnail.is_file() and case.expense.thumbnail_deleted_at is None
    assert case.expense.attachment_cleanup_request is None
    case.db.refresh.assert_not_called()  # Caller owns the existing row lock.
    case.db.commit.assert_not_called()  # Caller publishes metadata + receipt together.


def test_stale_request_id_cannot_consume_new_request(cleanup_case):
    case = cleanup_case
    current = _accept_only(case)
    before = deepcopy(case.expense.attachment_cleanup_request)
    case.db.refresh.reset_mock()
    case.db.commit.reset_mock()
    result = cleanup.settle_cleanup_request(case.db, case.expense, expected_request_id=uuid4())
    assert not result.changed and result.pending
    assert case.expense.attachment_cleanup_request == before
    assert cleanup.read_cleanup_request(case.expense).request_id == current.request_id
    assert case.original.is_file() and case.thumbnail.is_file()
    case.db.refresh.assert_not_called()
    case.db.commit.assert_not_called()


def test_automatic_continuation_does_not_consume_replacement_request_after_relock(cleanup_case):
    case = cleanup_case
    real_refresh = case.db.refresh.side_effect
    replacement_id = uuid4()

    def replace_request(*args, **kwargs):
        if case.commits == 1:
            # A separate owner completed/cancelled the old request and admitted
            # this later one while the automatic caller had released its lock.
            case.durable["attachment_cleanup_request"]["request_id"] = str(replacement_id)
        real_refresh(*args, **kwargs)

    case.db.refresh.side_effect = replace_request
    result = _run(case)
    assert not result.changed and result.pending
    assert cleanup.read_cleanup_request(case.expense).request_id == replacement_id
    assert case.original.is_file() and case.thumbnail.is_file() and case.commits == 1


def test_policy_is_read_again_after_durable_acceptance_before_unlink(cleanup_case):
    case = cleanup_case
    case.before_commit = lambda _number: setattr(case.settings, "delete_image_after_confirm", False)
    result = _run(case)
    assert result.pending and not result.changed
    assert case.durable["attachment_cleanup_request"] is not None
    assert case.original.is_file() and case.thumbnail.is_file() and case.commits == 1


def test_disabled_policy_never_admits_a_new_request(cleanup_case):
    case = cleanup_case
    case.settings.delete_image_after_confirm = False
    result = _run(case)
    assert not result.changed and not result.pending
    assert case.expense.attachment_cleanup_request is None and case.commits == 0
    assert case.original.is_file() and case.thumbnail.is_file()


def test_orphan_gc_retains_frozen_pending_paths_after_replenishment(cleanup_case):
    case = cleanup_case
    request = _accept_only(case)
    case.db.execute.return_value = [("uploads/owner/new.png", None, None, None, request.model_dump(mode="json"))]
    paths = cleanup_service._referenced_upload_paths(case.db, "owner")
    assert set(paths) == {"uploads/owner/new.png", request.image.reference, request.thumbnail.reference}


def test_thumbnail_claim_obeys_current_source_cleanup_but_not_old_source(cleanup_case):
    case = cleanup_case
    _accept_only(case)
    staged = SimpleNamespace(source_reference=case.expense.image_path, final_reference="uploads/owner/new-thumb.png")
    case.expense.thumbnail_path = None
    assert not claim_staged_thumbnail(case.expense, staged, replace_missing_reference=False)
    assert case.expense.thumbnail_path is None
    case.expense.image_path = staged.source_reference = "uploads/owner/replenished.png"
    assert claim_staged_thumbnail(case.expense, staged, replace_missing_reference=False)
    assert case.expense.thumbnail_path == staged.final_reference


@pytest.mark.parametrize("corrupt_request", [False, True])
def test_thumbnail_publication_loses_to_cleanup_and_discards_only_own_attempt(cleanup_case, monkeypatch, corrupt_request):
    case = cleanup_case
    staged = SimpleNamespace(source_reference=case.expense.image_path, final_reference=case.expense.thumbnail_path)
    publish, discard = Mock(), Mock()
    monkeypatch.setattr(thumb_service, "publish_staged_thumbnail_attempt", publish)
    monkeypatch.setattr(thumb_service, "discard_published_thumbnail_attempt", discard)
    request = _accept_only(case)
    if corrupt_request:
        case.db.refresh.side_effect = lambda *_a, **_k: set_committed_value(
            case.expense, "attachment_cleanup_request", {"invalid": "legacy corruption"})
        with pytest.raises(AppError) as error:
            publish_claimed_thumbnail(case.db, case.expense, staged)
        assert error.value.error == "attachment_cleanup_invalid"
        # Loading malformed metadata does not invoke the assignment validator,
        # and an unrelated financial field remains readable/editable.
        case.expense.merchant = "Corrected merchant"
        assert case.expense.merchant == "Corrected merchant"
    else:
        assert not publish_claimed_thumbnail(case.db, case.expense, staged)
        assert cleanup.read_cleanup_request(case.expense).request_id == request.request_id
    publish.assert_called_once_with(staged)
    discard.assert_called_once_with(staged)
    assert case.expense.image_deleted_at is None and case.expense.thumbnail_deleted_at is None
    assert case.original.is_file()


def test_initial_missing_file_is_not_admitted_as_intentional_cleanup(cleanup_case):
    case = cleanup_case
    case.original.unlink()
    result = _run(case)
    assert not result.changed and result.deleted_images == result.deleted_thumbnails == 0
    assert case.expense.attachment_cleanup_request is None
    assert case.expense.image_deleted_at is None and case.expense.thumbnail_deleted_at is None
    assert case.thumbnail.is_file() and case.commits == 0


@pytest.mark.parametrize("status", ["confirmed", "rejected"])
def test_replenishment_renews_retention_without_changing_financial_time(cleanup_case, status):
    case = cleanup_case
    case.expense.status = status
    case.expense.rejected_at = case.expense.confirmed_at
    original_time = getattr(case.expense, f"{status}_at")
    case.expense.image_replenished_at = now_utc()
    case.db.commit()
    operation = cleanup_service.cleanup_confirmed_images if status == "confirmed" else cleanup_service.cleanup_rejected_images
    result = operation(case.db, "owner")
    assert result.deleted_images == result.deleted_thumbnails == 0
    assert case.original.is_file() and case.thumbnail.is_file()
    assert getattr(case.expense, f"{status}_at") == original_time
    assert case.expense.attachment_cleanup_request is None
