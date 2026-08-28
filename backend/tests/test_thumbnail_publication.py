from __future__ import annotations

import pytest
from api_contract_helpers import upload_png
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.services.expense_service._enrich as enrich_service
from app.database import SessionLocal
from app.models import Expense
from app.services import thumb_service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_service import create_pending_expense
from app.services.expense_service._image import ensure_thumbnail_file
from app.services.file_service import save_upload_bytes
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
