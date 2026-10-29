from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

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
from app.models import ApiIdempotencyKey, BackgroundTask, Expense, UploadLink, UploadLinkDailyUsage
from app.services.currency_binding_service import resolve_write_capability
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


@pytest.mark.real_db
@pytest.mark.parametrize("budget", ["ledger_count", "bytes", "ledger_bytes", "disk"])
def test_durable_limits_preserve_accepted_receipts_and_refused_original_keys(client, monkeypatch, identity, budget):
    from app.config import get_settings
    from app.services import file_service

    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    keys = [str(uuid4()), str(uuid4())]

    def upload(key):
        return client.post("/api/app/upload-screenshot", content=PNG_BYTES,
            headers={**identity.app_headers, "Content-Type": "image/png", "Idempotency-Key": key})

    # A different ledger's task does not consume this ledger's allowance.
    if budget == "ledger_count":
        _seed_active_task(ledger_id="another-ledger")
    first = upload(keys[0])
    assert first.status_code == 200, first.text
    rows, files = _row_counts(), _stored_upload_files()
    variables = {"ledger_count": ("BACKGROUND_TASK_MAX_LEDGER_ACTIVE", "1"),
        "bytes": ("BACKGROUND_TASK_MAX_IMAGE_BYTES", str(len(PNG_BYTES) * 2 - 1)),
        "ledger_bytes": ("BACKGROUND_TASK_MAX_LEDGER_IMAGE_BYTES", str(len(PNG_BYTES) * 2 - 1))}
    with monkeypatch.context() as limits:
        if budget == "disk":
            free = get_settings().upload_min_free_bytes
            limits.setattr(file_service.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
        else:
            name, value = variables[budget]
            limits.setenv(name, value)
        reset_settings_cache()
        try:
            refused = upload(keys[1])
            assert refused.status_code == (507 if budget == "disk" else 503), refused.text
            assert refused.json()["error"] == ("upload_storage_full" if budget == "disk" else "enrichment_capacity_full")
            assert _row_counts() == rows and _stored_upload_files() == files
            with SessionLocal() as db:
                assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == keys[1])) is None
            replay = upload(keys[0])
            assert replay.status_code == 200 and replay.json() == first.json()
        finally:
            reset_settings_cache()
    reset_settings_cache()
    second = upload(keys[1])
    assert second.status_code == 200 and second.json()["id"] != first.json()["id"]
    assert upload(keys[1]).json() == second.json()
    assert _row_counts() == (rows[0] + 1, rows[1] + 1)


@pytest.mark.real_db
def test_busy_execution_slots_do_not_refuse_an_available_persistent_allowance(client, monkeypatch, identity):
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    with SessionLocal() as db:
        db.add_all([BackgroundTask(task_type=kind, tenant_id="owner", status="running")
            for kind in ("expense_enrichment", "csv_import")])
        db.commit()
    response = client.post("/api/app/upload-screenshot", content=PNG_BYTES,
        headers={**identity.app_headers, "Content-Type": "image/png", "Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == response.json()["enrichment_task_public_id"]))
        assert task.status == "queued" and task.source_expense_id == response.json()["id"]
        expense = db.get(Expense, task.source_expense_id)
        assert expense.status == "pending" and expense.image_hash == response.json()["image_hash"]


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
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    before_rows = _row_counts()
    before_files = _stored_upload_files()

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&idempotency_key=original-upload",
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
    identity,
) -> None:
    monkeypatch.setenv("BACKGROUND_TASK_MAX_ACTIVE", "1")
    reset_settings_cache()
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(tenant_id="owner", status="pending", source="截图上传",
            home_currency_code="CNY", original_currency_code="CNY", fx_status="ready")
        db.add(expense)
        db.commit()
        expense_id, row_version = expense.id, expense.row_version
    start = Barrier(2)

    def enqueue_once() -> str:
        with SessionLocal() as db:
            start.wait(timeout=5)
            try:
                prepare_pending_expense_enrichment(
                    db,
                    expense_id=expense_id,
                    tenant_id="owner",
                    timezone_name=None,
                    expected_row_version=row_version,
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
