from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from api_contract_helpers import upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

import app.services.expense_service._enrich as enrich_service
from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask, Expense
from app.services import background_task_service, cleanup_service, thumb_service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_service import create_pending_expense
from app.services.expense_service._image import ensure_thumbnail_file
from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.ocr_service import OcrExtraction, OcrResult
from app.services.pending_enrichment_task_service import PENDING_EXPENSE_ENRICHMENT_TASK_TYPE
from tests._infra.assets import PNG_BYTES


def _seed_pending_expense() -> tuple[int, int]:
    saved = save_upload_bytes(
        PNG_BYTES,
        tenant_id="owner",
        filename="receipt.png",
        content_type="image/png",
    )
    with SessionLocal() as db:
        expense = create_pending_expense(
            db,
            saved,
            "owner",
            source="网页上传",
        )
        return expense.id, expense.row_version


def _seed_queued_enrichment_task() -> tuple[int, int, int]:
    expense_id, row_version = _seed_pending_expense()
    with SessionLocal() as db:
        account_id = find_owner_account_id_for_ledger(db, ledger_id="owner")
        assert account_id is not None
        task = BackgroundTask(
            task_type=PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
            tenant_id="owner",
            initiated_by_account_id=account_id,
            status="queued",
            progress_total=1,
        )
        db.add(task)
        db.commit()
        return expense_id, row_version, task.id


def _ocr_result() -> list[OcrExtraction]:
    return [
        OcrExtraction(
            provider_name="mock",
            ocr_model="test-model",
            result=OcrResult(
                raw_text="盒马\n交易金额：19.90",
                confidence=0.98,
                amount_cents=1990,
                merchant="盒马",
            ),
        )
    ]


def _enable_delete_after_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, delete_image_after_confirm=True),
    )


@pytest.mark.real_db
def test_enrichment_commit_failure_never_publishes_staged_thumbnail(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version = _seed_pending_expense()
    staged_attempts = []
    real_stage_thumbnail = enrich_service._try_stage_thumbnail

    def capture_staged_attempt(*args, **kwargs):
        staged = real_stage_thumbnail(*args, **kwargs)
        assert staged is not None
        staged_attempts.append(staged)
        return staged

    real_commit = Session.commit
    rejected_publication = False

    def fail_publication_commit(db: Session) -> None:
        nonlocal rejected_publication
        expense = db.get(Expense, expense_id)
        if not rejected_publication and expense is not None and expense.thumbnail_path:
            rejected_publication = True
            raise SQLAlchemyError("thumbnail owner commit rejected")
        real_commit(db)

    monkeypatch.setattr(Session, "commit", fail_publication_commit)
    monkeypatch.setattr(
        enrich_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(enrich_service, "_try_stage_thumbnail", capture_staged_attempt)

    result = enrich_service.enrich_pending_expense(
        expense_id,
        "owner",
        expected_row_version=predecessor_row_version,
    )

    assert result.outcome == "failed"
    assert rejected_publication is True
    assert len(staged_attempts) == 1
    staged = staged_attempts[0]
    assert not staged.canonical_path.exists()
    assert not staged.staging_path.exists()
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.thumbnail_path is None
        assert expense.row_version == predecessor_row_version


@pytest.mark.real_db
def test_enrichment_commit_ack_loss_leaves_thumbnail_owner_self_healing(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version = _seed_pending_expense()
    staged_attempts = []
    real_stage_thumbnail = enrich_service._try_stage_thumbnail

    def capture_staged_attempt(*args, **kwargs):
        staged = real_stage_thumbnail(*args, **kwargs)
        assert staged is not None
        staged_attempts.append(staged)
        return staged

    real_commit = Session.commit
    acknowledgement_lost = False

    def commit_then_lose_acknowledgement(db: Session) -> None:
        nonlocal acknowledgement_lost
        expense = db.get(Expense, expense_id)
        if not acknowledgement_lost and expense is not None and expense.thumbnail_path:
            real_commit(db)
            acknowledgement_lost = True
            raise SQLAlchemyError("thumbnail owner commit acknowledgement lost")
        real_commit(db)

    monkeypatch.setattr(Session, "commit", commit_then_lose_acknowledgement)
    monkeypatch.setattr(
        enrich_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(enrich_service, "_try_stage_thumbnail", capture_staged_attempt)

    result = enrich_service.enrich_pending_expense(
        expense_id,
        "owner",
        expected_row_version=predecessor_row_version,
    )

    assert result.outcome == "failed"
    assert acknowledgement_lost is True
    assert len(staged_attempts) == 1
    staged = staged_attempts[0]
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.thumbnail_path == staged.canonical_reference
        assert expense.row_version == predecessor_row_version
    assert not staged.canonical_path.exists()
    assert not staged.staging_path.exists()
    with SessionLocal() as db:
        thumbnail_path, media_type = ensure_thumbnail_file(db, expense_id, "owner")
    assert thumbnail_path == staged.canonical_path
    assert thumbnail_path.is_file()
    assert media_type == "image/jpeg"


@pytest.mark.real_db
def test_thumbnail_get_commits_cache_owner_before_publishing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    previous_thumbnail = None
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        previous_thumbnail = thumb_service.resolve_protected_thumbnail(
            expense.thumbnail_path,
            "owner",
        )
        expense.thumbnail_path = None
        db.commit()
    if previous_thumbnail is not None:
        previous_thumbnail[0].unlink(missing_ok=True)

    real_publish = thumb_service.publish_staged_thumbnail
    owner_was_durable_before_publish = False

    def observe_publish(staged):
        nonlocal owner_was_durable_before_publish
        with SessionLocal() as probe_db:
            durable = probe_db.get(Expense, expense_id)
            assert durable is not None
            assert durable.thumbnail_path == staged.canonical_reference
        owner_was_durable_before_publish = True
        return real_publish(staged)

    monkeypatch.setattr(thumb_service, "publish_staged_thumbnail", observe_publish)

    response = client.get(
        f"/api/expenses/{expense_id}/thumbnail",
        headers=identity.app_headers,
    )

    assert response.status_code == 200
    assert owner_was_durable_before_publish is True


@pytest.mark.real_db
def test_enrichment_staging_cleanup_failure_preserves_completed_task_truth(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version, task_id = _seed_queued_enrichment_task()
    staged_attempts = []
    real_unlink = Path.unlink

    def fail_publication(staged):
        staged_attempts.append(staged)
        raise OSError("thumbnail publication unavailable")

    def deny_staging_cleanup(path: Path, *args, **kwargs):
        if any(path == staged.staging_path for staged in staged_attempts):
            raise PermissionError("thumbnail staging file is locked")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(
            enrich_service,
            "collect_auto_ocr_extractions",
            lambda *_args, **_kwargs: _ocr_result(),
        )
        failure.setattr(enrich_service, "publish_staged_thumbnail", fail_publication)
        failure.setattr(Path, "unlink", deny_staging_cleanup)
        background_task_service._run_task(  # noqa: SLF001 - exercise the real worker truth barrier.
            task_id,
            {
                "expense_id": expense_id,
                "tenant_id": "owner",
                "timezone_name": None,
                "expected_row_version": predecessor_row_version,
            },
        )

    for staged in staged_attempts:
        real_unlink(staged.staging_path, missing_ok=True)
    assert len(staged_attempts) == 1
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        expense = db.get(Expense, expense_id)
        assert task is not None
        assert task.status == "completed"
        assert expense is not None
        assert expense.amount_cents == 1990
        assert expense.merchant == "盒马"


@pytest.mark.real_db
def test_thumbnail_get_rechecks_cleanup_after_staging(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    _enable_delete_after_confirm(monkeypatch)
    expense_id, _row_version = _seed_pending_expense()
    staged_attempts = []
    real_stage_thumbnail = thumb_service.stage_thumbnail

    def stage_then_cleanup(*args, **kwargs):
        staged = real_stage_thumbnail(*args, **kwargs)
        assert staged is not None
        staged_attempts.append(staged)
        with SessionLocal() as cleanup_db:
            expense = cleanup_db.get(Expense, expense_id)
            assert expense is not None
            assert cleanup_service.cleanup_after_confirm(cleanup_db, expense) is True
            cleanup_db.commit()
        return staged

    monkeypatch.setattr(thumb_service, "stage_thumbnail", stage_then_cleanup)

    with SessionLocal() as db, pytest.raises(AppError) as caught:
        ensure_thumbnail_file(db, expense_id, "owner")

    assert caught.value.error == "image_not_found"
    assert len(staged_attempts) == 1
    staged = staged_attempts[0]
    assert not staged.canonical_path.exists()
    assert not staged.staging_path.exists()
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_deleted_at is not None
        assert expense.thumbnail_path is None


@pytest.mark.real_db
def test_cleanup_defers_when_durable_thumbnail_is_not_yet_published(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    _enable_delete_after_confirm(monkeypatch)
    expense_id, _row_version = _seed_pending_expense()
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        source = resolve_upload_path_for_tenant(expense.image_path, "owner")
        staged = thumb_service.stage_thumbnail(expense.image_path, tenant_id="owner")
        assert source is not None
        assert staged is not None
        thumb_service.discard_staged_thumbnail(staged)
        authorize_currency_metadata_write(db)
        expense.thumbnail_path = staged.canonical_reference
        db.commit()

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert cleanup_service.cleanup_after_confirm(db, expense) is False
        db.commit()

    assert source.is_file()
    assert not staged.canonical_path.exists()
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_deleted_at is None
        assert expense.thumbnail_deleted_at is None


@pytest.mark.real_db
def test_cleanup_locks_expense_before_file_deletion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    _enable_delete_after_confirm(monkeypatch)
    expense_id, _row_version = _seed_pending_expense()
    real_delete = cleanup_service._delete_relative_file_for_db_mark
    lock_observed = False

    def observe_expense_lock(relative_path: str | None, tenant_id: str):
        nonlocal lock_observed
        with SessionLocal() as probe_db:
            try:
                probe_db.scalar(
                    select(Expense.id)
                    .where(Expense.id == expense_id, Expense.tenant_id == "owner")
                    .with_for_update(nowait=True)
                )
            except OperationalError:
                probe_db.rollback()
                lock_observed = True
            else:
                probe_db.rollback()
        return real_delete(relative_path, tenant_id)

    monkeypatch.setattr(
        cleanup_service,
        "_delete_relative_file_for_db_mark",
        observe_expense_lock,
    )

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert cleanup_service.cleanup_after_confirm(db, expense) is True
        db.commit()

    assert lock_observed is True
