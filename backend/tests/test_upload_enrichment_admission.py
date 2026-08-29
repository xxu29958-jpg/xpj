from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import pytest
from api_contract_helpers import _stored_upload_files
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import BackgroundTask, Expense, UploadLink, UploadLinkDailyUsage
from app.services import background_task_service
from app.services.identity_service import hash_secret
from app.services.pending_enrichment_task_service import prepare_pending_expense_enrichment
from tests._infra.assets import PNG_BYTES


def _row_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        expense_count = int(db.scalar(select(func.count()).select_from(Expense)) or 0)
        task_count = int(db.scalar(select(func.count()).select_from(BackgroundTask)) or 0)
    return expense_count, task_count


def _seed_active_task(*, ledger_id: str = "owner") -> int:
    with SessionLocal() as db:
        task = BackgroundTask(
            task_type="expense_enrichment",
            tenant_id=ledger_id,
            initiated_by_account_id=None,
            progress_total=1,
        )
        db.add(task)
        db.commit()
        return task.id


@pytest.fixture()
def one_active_task_capacity(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BACKGROUND_TASK_MAX_ACTIVE", "1")
    reset_settings_cache()
    active_task_id = _seed_active_task()
    try:
        yield active_task_id
    finally:
        reset_settings_cache()


@pytest.mark.real_db
def test_task_row_flush_failure_rolls_back_pending_and_deletes_saved_file(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    """A deterministic task-stage failure must not publish half an upload."""

    before_rows = _row_counts()
    before_files = _stored_upload_files()
    real_flush = Session.flush

    def fail_background_task_flush(db: Session, *args, **kwargs) -> None:
        if any(isinstance(row, BackgroundTask) for row in db.new):
            raise SQLAlchemyError("background task insert unavailable")
        real_flush(db, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail_background_task_flush)

    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.post(
            "/api/app/upload-screenshot",
            headers={**identity.app_headers, "Content-Type": "image/png"},
            content=PNG_BYTES,
        )

    assert response.status_code == 500
    assert response.json()["error"] == "server_error"
    assert _row_counts() == before_rows
    assert _stored_upload_files() == before_files


@pytest.mark.real_db
@pytest.mark.parametrize("consumer", ["android", "upload_link"])
def test_full_enrichment_capacity_rejects_before_any_upload_artifact_is_durable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    one_active_task_capacity: int,
    *,
    identity,
    consumer: str,
) -> None:
    del one_active_task_capacity
    monkeypatch.setattr(background_task_service, "_submit_task", lambda *_args, **_kwargs: None)
    before_rows = _row_counts()
    before_files = _stored_upload_files()
    path = "/api/app/upload-screenshot" if consumer == "android" else identity.upload_url_path
    headers = identity.app_headers if consumer == "android" else identity.upload_headers

    response = client.post(
        path,
        headers={**headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )

    assert response.status_code == 503
    assert response.json()["error"] == "enrichment_capacity_full"
    assert _row_counts() == before_rows
    assert _stored_upload_files() == before_files


@pytest.mark.real_db
def test_web_capacity_rejection_returns_to_pending_with_honest_flash(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    one_active_task_capacity: int,
) -> None:
    del one_active_task_capacity
    monkeypatch.setattr(background_task_service, "_submit_task", lambda *_args, **_kwargs: None)
    before_rows = _row_counts()
    before_files = _stored_upload_files()

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["flash_type"] == ["error"]
    assert query["msg"] == ["识别队列暂时已满，这张小票还没有保存；请稍等片刻重新选择上传。"]
    assert "watch" not in query
    pending = web_client.get(response.headers["location"])
    assert pending.status_code == 200
    assert "识别队列暂时已满，这张小票还没有保存；请稍等片刻重新选择上传。" in pending.text
    assert 'class="product-feedback product-feedback--error"' in pending.text
    assert 'role="alert"' in pending.text
    assert _row_counts() == before_rows
    assert _stored_upload_files() == before_files


@pytest.mark.real_db
def test_capacity_rejection_releases_upload_link_byte_reservation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    one_active_task_capacity: int,
    *,
    identity,
) -> None:
    del one_active_task_capacity
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", str(len(PNG_BYTES)))
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "0")
    reset_settings_cache()
    try:
        response = client.post(
            identity.upload_url_path,
            headers={**identity.upload_headers, "Content-Type": "image/png"},
            content=PNG_BYTES,
        )

        assert response.status_code == 503
        assert response.json()["error"] == "enrichment_capacity_full"
        with SessionLocal() as db:
            link = db.scalar(select(UploadLink).where(UploadLink.token_hash == hash_secret(identity.upload_key)))
            assert link is not None
            usage = db.scalar(
                select(UploadLinkDailyUsage).where(UploadLinkDailyUsage.upload_link_id == link.id)
            )
            assert usage is not None
            assert usage.bytes_total == 0
            assert usage.request_count == 0
    finally:
        reset_settings_cache()


@pytest.mark.real_db
def test_concurrent_enqueues_share_one_postgres_capacity_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACKGROUND_TASK_MAX_ACTIVE", "1")
    reset_settings_cache()
    monkeypatch.setattr(background_task_service, "_submit_task", lambda *_args, **_kwargs: None)
    start = Barrier(2)

    def enqueue_once() -> str:
        with SessionLocal() as db:
            start.wait(timeout=5)
            try:
                prepare_pending_expense_enrichment(
                    db,
                    expense_id=1,
                    tenant_id="owner",
                    timezone_name=None,
                    expected_row_version=1,
                    initiator_account_id=None,
                    initiator_device_id=None,
                )
                db.commit()
            except AppError as exc:
                return exc.error
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(enqueue_once) for _ in range(2)]
            outcomes = sorted(future.result() for future in futures)
    finally:
        reset_settings_cache()

    assert outcomes == ["created", "enrichment_capacity_full"]
    with SessionLocal() as db:
        active_count = int(
            db.scalar(
                select(func.count())
                .select_from(BackgroundTask)
                .where(BackgroundTask.status.in_(("queued", "running")))
            )
            or 0
        )
    assert active_count == 1
