from __future__ import annotations

import json
from io import BytesIO

import pytest
from api_contract_helpers import _stored_upload_files
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import ApiIdempotencyKey, BackgroundTask, Expense
from tests._infra.assets import PNG_BYTES


def _ledger_upload_row_counts(ledger_id: str) -> tuple[int, int]:
    with SessionLocal() as db:
        expenses = db.scalar(select(func.count()).select_from(Expense).where(Expense.tenant_id == ledger_id))
        tasks = db.scalar(select(func.count()).select_from(BackgroundTask).where(BackgroundTask.tenant_id == ledger_id))
        return int(expenses or 0), int(tasks or 0)


def _capture_enrichment_execution(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, dict]]:
    from app.services import background_task_worker

    executions: list[tuple[int, dict]] = []

    def execute(task_id, payload, *, registry, runner):
        del registry, runner
        with SessionLocal() as db:
            if background_task_worker.claim_queued_task(db, task_id) is not None:
                executions.append((task_id, dict(payload)))

    monkeypatch.setattr("app.services.background_task_executor.submit_task", execute)
    return executions


def test_upload_receipt_key_is_optional_without_weakening_outbox_command_headers() -> None:
    app.openapi_schema = None
    spec = app.openapi()
    key_headers = {
        (path, method): parameter
        for path, path_item in spec["paths"].items()
        for method, operation in path_item.items()
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header" and parameter.get("name") == "Idempotency-Key"
    }
    upload_key = key_headers.pop(("/api/app/upload-screenshot", "post"))
    assert upload_key["required"] is False
    assert "x-ticketbox-runtime-required" not in upload_key["schema"]
    assert key_headers
    assert all(parameter["required"] for parameter in key_headers.values())


@pytest.mark.real_db
def test_android_upload_same_intent_returns_the_original_receipt_without_another_expense_or_task(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    submissions = _capture_enrichment_execution(monkeypatch)
    before_rows = _ledger_upload_row_counts("owner")
    before_files = set(_stored_upload_files())
    headers = {
        **identity.app_headers,
        "Idempotency-Key": "70000000-0000-4000-8000-000000000010",
        "X-Timezone": "America/Los_Angeles",
    }
    files = {"file": ("original-receipt.png", PNG_BYTES, "image/png")}
    first = client.post("/api/app/upload-screenshot", headers=headers, files=files)
    assert first.status_code == 200, first.text
    receipt = first.json()
    first_rows = _ledger_upload_row_counts("owner")
    first_files = set(_stored_upload_files())
    assert first_rows == (before_rows[0] + 1, before_rows[1] + 1)
    assert first_files > before_files
    assert len(submissions) == 1
    assert submissions[0][1]["timezone_name"] == "America/Los_Angeles"
    assert submissions[0][1]["expense_id"] == receipt["id"]

    # The caller no longer knows whether this already-committed first response arrived.
    replay = client.post("/api/app/upload-screenshot", headers=headers, files=files)
    assert replay.status_code == 200, replay.text
    receipt_fields = ("id", "public_id", "enrichment_task_public_id", "status", "message")
    assert {key: replay.json()[key] for key in receipt_fields} == {key: receipt[key] for key in receipt_fields}
    assert _ledger_upload_row_counts("owner") == first_rows
    assert set(_stored_upload_files()) == first_files
    assert len(submissions) == 1

    # A separate intent may deliberately upload the same image; duplicate review still owns that decision.
    distinct = client.post("/api/app/upload-screenshot",
        headers={**headers, "Idempotency-Key": "70000000-0000-4000-8000-000000000011"}, files=files)
    assert distinct.status_code == 200, distinct.text
    assert distinct.json()["id"] != receipt["id"]
    assert distinct.json()["enrichment_task_public_id"] != receipt["enrichment_task_public_id"]
    assert _ledger_upload_row_counts("owner") == (first_rows[0] + 1, first_rows[1] + 1)
    assert len(submissions) == 2
    with SessionLocal() as db:
        expense = db.get(Expense, distinct.json()["id"])
        original = db.get(Expense, receipt["id"])
        assert expense is not None and original is not None
        assert expense.tenant_id == original.tenant_id == "owner"
        assert expense.duplicate_status == "suspected"
        assert expense.duplicate_of_id == original.id
        assert expense.image_hash == original.image_hash


@pytest.mark.real_db
@pytest.mark.parametrize("changed", ["raw_metadata", "timezone", "filename", "content_type"])
def test_android_upload_key_rejects_changed_original_input_before_saving_again(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity, changed: str,
) -> None:
    from PIL import Image, PngImagePlugin

    from app.routes import _upload_request

    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    headers = {**identity.app_headers, "Idempotency-Key": "70000000-0000-4000-8000-000000000020",
        "X-Timezone": "America/Los_Angeles"}
    response = client.post("/api/app/upload-screenshot", headers=headers,
        files={"file": ("original.png", PNG_BYTES, "image/png")})
    assert response.status_code == 200
    original_rows = _ledger_upload_row_counts("owner")
    original_files = _stored_upload_files()
    data, filename, media_type = PNG_BYTES, "original.png", "image/png"
    if changed == "raw_metadata":
        output = BytesIO()
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "different raw input, identical pixels")
        with Image.open(BytesIO(PNG_BYTES)) as image:
            image.save(output, format="PNG", pnginfo=metadata)
        data = output.getvalue()
        assert data != PNG_BYTES
    elif changed == "timezone":
        headers["X-Timezone"] = "Asia/Shanghai"
    elif changed == "filename":
        filename = "another.png"
    else:
        media_type = "application/octet-stream"

    def must_not_save(*_args, **_kwargs):
        raise AssertionError("A reused key must be rejected before persistent file creation")

    monkeypatch.setattr(_upload_request, "save_upload_bytes", must_not_save)
    replay = client.post("/api/app/upload-screenshot", headers=headers, files={"file": (filename, data, media_type)})
    assert replay.status_code == 422
    assert replay.json()["error"] == "idempotency_key_reused"
    assert _ledger_upload_row_counts("owner") == original_rows
    assert _stored_upload_files() == original_files


@pytest.mark.real_db
def test_android_upload_receipt_claim_failure_rolls_back_its_expense_task_and_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    from app.routes import _upload_request

    submissions: list[int] = []
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, *_args, **_kwargs: submissions.append(task_id))
    before_rows, before_files = _ledger_upload_row_counts("owner"), _stored_upload_files()
    key = "70000000-0000-4000-8000-000000000021"
    headers = {**identity.app_headers, "Idempotency-Key": key, "Content-Type": "image/png"}
    original_mark = _upload_request.mark_idempotency_succeeded

    def fail_receipt_flush(db, row, **_kwargs):
        assert row.status == "in_progress"
        assert db.scalar(select(func.count()).select_from(Expense).where(Expense.tenant_id == "owner")) == before_rows[0] + 1
        raise RuntimeError("receipt flush unavailable before the upload commit")

    monkeypatch.setattr(_upload_request, "mark_idempotency_succeeded", fail_receipt_flush)
    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        failed = no_raise_client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert failed.status_code == 500
    assert _ledger_upload_row_counts("owner") == before_rows
    assert _stored_upload_files() == before_files
    assert submissions == []
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None

    monkeypatch.setattr(_upload_request, "mark_idempotency_succeeded", original_mark)
    retry = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert retry.status_code == 200
    assert _ledger_upload_row_counts("owner") == (before_rows[0] + 1, before_rows[1] + 1)
    assert len(submissions) == 1
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert claim is not None and claim.status == "succeeded"
        assert claim.response_body == retry.json()


@pytest.mark.real_db
@pytest.mark.parametrize("readback_available,restart_before_retry", [(True, False), (False, False), (False, True)])
def test_android_upload_lost_commit_ack_recovers_its_original_task_and_receipt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity, readback_available: bool, restart_before_retry: bool,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    from app.routes import _upload_request

    submissions = _capture_enrichment_execution(monkeypatch)
    before_rows, before_files = _ledger_upload_row_counts("owner"), _stored_upload_files()
    key = "70000000-0000-4000-8000-000000000022"
    headers = {**identity.app_headers, "Idempotency-Key": key, "Content-Type": "image/png",
        "X-Timezone": "America/Los_Angeles"}
    original_commit = Session.commit
    lost_ack = False

    def commit_then_lose_ack(db):
        nonlocal lost_ack
        upload_commit = any(isinstance(row, ApiIdempotencyKey) and row.idempotency_key == key
            and row.status == "succeeded" for row in db.identity_map.values())
        original_commit(db)
        if upload_commit and not lost_ack:
            lost_ack = True
            raise SQLAlchemyError("upload commit acknowledgement lost")

    monkeypatch.setattr(Session, "commit", commit_then_lose_ack)
    if not readback_available:
        def unavailable_readback(*_args):
            raise SQLAlchemyError("commit read-back temporarily unavailable")
        monkeypatch.setattr(_upload_request, "upload_commit_is_durable", unavailable_readback)
    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        accepted = no_raise_client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert lost_ack
    assert accepted.status_code == (200 if readback_available else 500)
    accepted_files = _stored_upload_files()
    assert set(accepted_files) > set(before_files)
    assert _ledger_upload_row_counts("owner") == (before_rows[0] + 1, before_rows[1] + 1)
    assert len(submissions) == (1 if readback_available else 0)
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert claim is not None and claim.status == "succeeded"
        receipt = claim.response_body
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        assert task is not None
        expected_submission = (task.id, {
            "expense_id": receipt["id"], "tenant_id": "owner", "timezone_name": "America/Los_Angeles",
            "expected_row_version": 1,
        })
        assert json.loads(task.input_payload_json) == expected_submission[1]
        if readback_available:
            assert submissions == [expected_submission]
            assert accepted.json() == receipt
        else:
            from app.services.currency_binding_service import resolve_write_capability
            from app.services.optimistic_concurrency import bump_row_version

            resolve_write_capability(db)
            expense = db.get(Expense, receipt["id"])
            expense.merchant = "用户在回执重试前修改"
            bump_row_version(expense)
            db.commit()

    monkeypatch.setattr(Session, "commit", original_commit)
    if restart_before_retry:
        from app.services.background_task_service import recover_orphaned_tasks

        assert recover_orphaned_tasks() >= 1
        with SessionLocal() as db:
            task = db.get(BackgroundTask, expected_submission[0])
            assert (task.status, task.error_code) == ("failed", "orphaned_after_restart")
    replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert replay.status_code == 200
    assert replay.json() == receipt
    assert _ledger_upload_row_counts("owner") == (before_rows[0] + 1, before_rows[1] + 1)
    assert _stored_upload_files() == accepted_files
    assert submissions == [expected_submission], "Receipt replay must recover an original task that was never submitted"


@pytest.mark.real_db
@pytest.mark.parametrize("blocker", ["capacity", "cancellation", "handler_failure", "completed"])
def test_restart_replay_respects_capacity_cancellation_and_terminal_outcomes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity, blocker: str,
) -> None:
    from app.config import reset_settings_cache
    from app.services.time_service import now_utc

    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    headers = {**identity.app_headers, "Idempotency-Key": "70000000-0000-4000-8000-000000000025",
        "Content-Type": "image/png"}
    first = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert first.status_code == 200
    receipt = first.json()
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        task.status, task.error_code, task.completed_at = "failed", "orphaned_after_restart", now_utc()
        task_id, original_input = task.id, task.input_payload_json
        if blocker == "capacity":
            other = BackgroundTask(task_type="expense_enrichment", tenant_id="owner", status="queued")
            db.add(other)
            db.flush()
            other_id = other.id
        elif blocker == "cancellation":
            task.cancellation_requested_at = now_utc()
        elif blocker == "handler_failure":
            task.error_code = "PendingEnrichmentTaskError"
        else:
            task.status = "completed"
        db.commit()
    executions = _capture_enrichment_execution(monkeypatch)
    rows, files = _ledger_upload_row_counts("owner"), _stored_upload_files()
    monkeypatch.setenv("BACKGROUND_TASK_MAX_ACTIVE", "1")
    reset_settings_cache()
    try:
        replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
        assert replay.status_code == (503 if blocker == "capacity" else 200)
        assert executions == []
        if blocker == "capacity":
            assert replay.json()["error"] == "enrichment_capacity_full"
            with SessionLocal() as db:
                task = db.get(BackgroundTask, task_id)
                assert (task.status, task.error_code) == ("failed", "orphaned_after_restart")
                db.get(BackgroundTask, other_id).status = "cancelled"
                db.commit()
            for _ in range(2):
                replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
                assert replay.status_code == 200
                assert replay.json() == receipt
            assert executions == [(task_id, json.loads(original_input))]
        else:
            assert replay.json() == receipt
        assert _ledger_upload_row_counts("owner") == rows
        assert _stored_upload_files() == files
    finally:
        monkeypatch.delenv("BACKGROUND_TASK_MAX_ACTIVE")
        reset_settings_cache()


@pytest.mark.real_db
def test_original_task_replay_wakes_a_concurrently_readmitted_original(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    from app.services import background_task_recovery_service, background_task_service, pending_enrichment_task_service
    from app.services.time_service import now_utc

    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    headers = {**identity.app_headers, "Idempotency-Key": "70000000-0000-4000-8000-000000000026",
        "Content-Type": "image/png"}
    first = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert first.status_code == 200
    receipt = first.json()
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        task.created_at = now_utc() - timedelta(days=1)
        db.commit()
    assert background_task_service.recover_orphaned_tasks() >= 1
    rows, files = _ledger_upload_row_counts("owner"), _stored_upload_files()
    executions = _capture_enrichment_execution(monkeypatch)
    readmit = pending_enrichment_task_service.readmit_orphaned_task

    def commit_concurrent_readmission(db, task_id):
        # The caller already read failed; another real connection commits the
        # original's queued phase but never wakes its worker (lost acknowledgement).
        with SessionLocal() as concurrent_db:
            assert readmit(concurrent_db, task_id).status == "queued"
            concurrent_db.commit()
        # A different worker starting within the configured admission grace must
        # observe fresh activity, not mistake the original creation time for it.
        settings = background_task_recovery_service.get_settings()
        with monkeypatch.context() as recovery_context:
            recovery_context.setattr(background_task_recovery_service, "get_settings",
                lambda: replace(settings, background_task_orphan_grace_seconds=60))
            background_task_recovery_service.recover_orphaned_tasks()
        with SessionLocal() as observed_db:
            assert observed_db.get(BackgroundTask, task_id).status == "queued"
        return readmit(db, task_id)

    monkeypatch.setattr(pending_enrichment_task_service, "readmit_orphaned_task", commit_concurrent_readmission)
    for _ in range(2):
        replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
        assert replay.status_code == 200
        assert replay.json() == receipt
    assert len(executions) == 1
    with SessionLocal() as db:
        task = db.get(BackgroundTask, executions[0][0])
        assert task.public_id == receipt["enrichment_task_public_id"]
        assert executions[0][1] == json.loads(task.input_payload_json)
        assert task.status == "running"
    assert _ledger_upload_row_counts("owner") == rows
    assert _stored_upload_files() == files


@pytest.mark.real_db
@pytest.mark.parametrize("task_status,invalid_input", [
    ("running", None), ("completed", None), ("failed", None), ("cancelled", None),
    ("queued", None), ("queued", "invalid-json"), ("queued", "wrong-expense"),
])
def test_receipt_replay_preserves_terminal_tasks_and_exposes_unrecoverable_original_input(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity, task_status, invalid_input,
) -> None:
    submissions = []
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, *_args, **_kwargs: submissions.append(task_id))
    headers = {**identity.app_headers, "Idempotency-Key": "70000000-0000-4000-8000-000000000024",
        "Content-Type": "image/png"}
    first = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert first.status_code == 200
    receipt = first.json()
    assert len(submissions) == 1
    rows, files = _ledger_upload_row_counts("owner"), _stored_upload_files()
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        task.status = task_status
        if invalid_input == "wrong-expense":
            payload = json.loads(task.input_payload_json)
            payload["expense_id"] += 1
            task.input_payload_json = json.dumps(payload)
        else:
            task.input_payload_json = invalid_input
        db.commit()
    replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert replay.status_code == 200
    assert replay.json() == receipt
    assert len(submissions) == 1
    assert _ledger_upload_row_counts("owner") == rows
    assert _stored_upload_files() == files
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        assert task.status == ("failed" if task_status == "queued" else task_status)
        assert task.error_code == ("task_input_unavailable" if task_status == "queued" else None)


@pytest.mark.real_db
def test_android_upload_uncommitted_attempt_cannot_submit_or_return_a_receipt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    submissions: list[int] = []
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, *_args, **_kwargs: submissions.append(task_id))
    before_rows, before_files = _ledger_upload_row_counts("owner"), set(_stored_upload_files())
    key = "70000000-0000-4000-8000-000000000023"
    headers = {**identity.app_headers, "Idempotency-Key": key, "Content-Type": "image/png"}
    original_commit = Session.commit
    commit_attempted = False

    def reject_upload_commit(db):
        nonlocal commit_attempted
        if any(isinstance(row, ApiIdempotencyKey) and row.idempotency_key == key
            and row.status == "succeeded" for row in db.identity_map.values()):
            commit_attempted = True
            raise SQLAlchemyError("upload transaction was not committed")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", reject_upload_commit)
    with TestClient(app, raise_server_exceptions=False) as no_raise_client:
        failed = no_raise_client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert commit_attempted
    assert failed.status_code == 500
    assert _ledger_upload_row_counts("owner") == before_rows
    assert set(_stored_upload_files()) > before_files, "An uncertain commit preserves its original attachment"
    assert submissions == []
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None

    monkeypatch.setattr(Session, "commit", original_commit)
    retry = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert retry.status_code == 200
    assert _ledger_upload_row_counts("owner") == (before_rows[0] + 1, before_rows[1] + 1)
    assert len(submissions) == 1
