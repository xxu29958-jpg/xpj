"""Business counterexamples for connection-free compute and atomic OCR receipts."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BackgroundTask, Expense, LedgerMember, OcrFact
from app.services import background_task_service, background_task_worker
from app.services.expense_service import _enrich
from app.services.pending_enrichment_task_service import run_pending_expense_enrichment_task
from app.services.time_service import now_utc
from tests.test_pending_enrichment_task_service import _ocr_result, _seed_pending_enrichment_task

pytestmark = pytest.mark.real_db


def _payload(expense_id, predecessor):
    return {"expense_id": expense_id, "tenant_id": "owner", "timezone_name": "Asia/Shanghai",
            "expected_row_version": predecessor}


def test_compute_has_no_task_transaction_or_session_bound_expense(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as task_db:
        task = task_db.get(BackgroundTask, task_id)

        def extract(expense, **kwargs):
            assert inspect(expense).transient
            assert not task_db.in_transaction(), "Inference retained the handler's read transaction"
            return _ocr_result()

        monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", extract)
        monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
        run_pending_expense_enrichment_task(task_db, task, _payload(expense_id, predecessor))
        assert json.loads(task.result_summary_json)["row_version"] == predecessor + 1


def test_applied_receipt_and_fact_survive_lost_commit_acknowledgement(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.status = "queued"
        db.commit()
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: _ocr_result())
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    original_commit = Session.commit
    observed = []

    def commit_then_lose_ack(db):
        applied = any(isinstance(row, BackgroundTask) and row.id == task_id
                      and row.result_summary_json is not None for row in db.dirty)
        if applied and not observed:
            with SessionLocal() as observer:
                assert observer.get(Expense, expense_id).row_version == predecessor
                assert observer.get(BackgroundTask, task_id).result_summary_json is None
            original_commit(db)
            with SessionLocal() as observer:
                assert observer.get(Expense, expense_id).row_version == predecessor + 1
                assert json.loads(observer.get(BackgroundTask, task_id).result_summary_json)["row_version"] == predecessor + 1
                assert observer.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 1
            observed.append(True)
            raise SQLAlchemyError("synthetic lost commit acknowledgement")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", commit_then_lose_ack)
    background_task_worker.run_task(task_id, _payload(expense_id, predecessor))
    assert observed == [True]
    with SessionLocal() as db:
        assert db.get(BackgroundTask, task_id).status == "completed"
        assert db.get(Expense, expense_id).row_version == predecessor + 1
        assert db.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 1


def test_revoked_write_membership_during_compute_cannot_apply(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        account_id = task.initiated_by_account_id
        task.status = "queued"
        db.commit()

    def revoke(*_args, **_kwargs):
        with SessionLocal() as db:
            membership = db.scalar(select(LedgerMember).where(LedgerMember.account_id == account_id,
                                                            LedgerMember.ledger_id == "owner"))
            membership.disabled_at = now_utc()
            db.commit()
        return _ocr_result()

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", revoke)
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    background_task_worker.run_task(task_id, _payload(expense_id, predecessor))
    with SessionLocal() as db:
        assert db.get(BackgroundTask, task_id).status == "failed"
        assert db.get(BackgroundTask, task_id).result_summary_json is None
        assert db.get(Expense, expense_id).row_version == predecessor
        assert db.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 0


def test_cancel_after_applied_receipt_does_not_claim_cancellation(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: _ocr_result())
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        run_pending_expense_enrichment_task(db, task, _payload(expense_id, predecessor))
        result = task.result_summary_json
        cancelled = background_task_service.request_cancellation(db, task.public_id, account_id=None, tenant_id=None)
        assert cancelled.result_summary_json == result
        assert cancelled.cancellation_requested_at is None
        assert db.get(Expense, expense_id).row_version == predecessor + 1


def test_image_evidence_is_preserved_with_the_fact_and_task_receipt(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        source_digest = db.get(Expense, expense_id).image_hash
    evidence = {"schema": "text-blocks/v1", "input_sha256": source_digest,
                "width": 1, "height": 1, "coordinate_space": "exif-transposed-pixels",
                "blocks": [{"text": "盒马", "confidence": 0.98, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
                "identity": {"recipe_sha256": "frozen-recipe"}}
    extraction = _ocr_result()[0]
    extraction = replace(extraction, result=replace(extraction.result, evidence=evidence))
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: [extraction])
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        run_pending_expense_enrichment_task(db, task, _payload(expense_id, predecessor))
    with SessionLocal() as observer:
        fact = observer.scalar(select(OcrFact).where(OcrFact.expense_id == expense_id))
        recorded = json.loads(fact.evidence_json)
        field_parse = recorded.pop("field_parse")
        assert recorded == evidence
        amount = next(item for item in field_parse["candidates"] if item["field"] == "amount_cents")
        assert amount["value"] == 1990
        assert extraction.result.raw_text[slice(*amount["raw_spans"][0])] == "交易金额：19.90"
        assert fact.raw_text == extraction.result.raw_text
        assert json.loads(observer.get(BackgroundTask, task_id).result_summary_json)["row_version"] == predecessor + 1


@pytest.mark.parametrize("applied", [False, True])
def test_original_receipt_recovers_submission_refusal_without_duplicate_application(identity, monkeypatch, applied):
    from app.services.pending_enrichment_task_service import resume_pending_expense_enrichment

    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    payload = _payload(expense_id, predecessor)
    calls = []

    def extract(*_args, **_kwargs):
        calls.append(expense_id)
        return _ocr_result()

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", extract)
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.input_payload_json = json.dumps(payload)
        db.commit()
        if applied:
            run_pending_expense_enrichment_task(db, task, payload)
        task.status, task.error_code = "failed", "task_submission_failed"
        db.commit()
        public_id = task.public_id
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
                        lambda task_id, payload, *, registry, runner: runner(task_id, payload, registry))
    for _ in range(2):
        with SessionLocal() as db:
            resume_pending_expense_enrichment(db, task_public_id=public_id, expense_id=expense_id, tenant_id="owner")
    with SessionLocal() as db:
        assert db.get(BackgroundTask, task_id).status == "completed"
        assert db.get(Expense, expense_id).row_version == predecessor + 1
        assert db.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 1
    assert calls == [expense_id]


def test_cancel_racing_an_apply_waits_for_the_same_receipt_lock(identity, monkeypatch):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.status = "queued"
        public_id = task.public_id
        db.commit()
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: _ocr_result())
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    real_commit = _enrich._commit_result
    started, backend_pid, futures = Event(), [], []

    def cancel():
        with SessionLocal() as db:
            backend_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            result = background_task_service.request_cancellation(db, public_id, account_id=None, tenant_id=None)
            return result.cancellation_requested_at

    with ThreadPoolExecutor(max_workers=1) as pool:
        def commit_while_cancel_is_waiting(db, task, result):
            futures.append(pool.submit(cancel))
            assert started.wait(5)
            deadline = time.monotonic() + 5
            while True:
                with SessionLocal() as observer:
                    blocked = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                              {"pid": backend_pid[0]})
                if blocked:
                    break
                assert time.monotonic() < deadline, "Cancellation did not wait on the atomic apply lock"
                time.sleep(0.01)
            return real_commit(db, task, result)

        monkeypatch.setattr(_enrich, "_commit_result", commit_while_cancel_is_waiting)
        background_task_worker.run_task(task_id, _payload(expense_id, predecessor))
        assert futures[0].result(timeout=5) is None
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "completed" and task.cancellation_requested_at is None
        assert db.get(Expense, expense_id).row_version == predecessor + 1


def test_original_bytes_replaced_during_compute_cannot_publish_evidence(identity, monkeypatch):
    from app.services.file_service import resolve_upload_path_for_tenant

    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.status = "queued"
        source = db.get(Expense, expense_id)
        source_path = resolve_upload_path_for_tenant(source.image_path, source.tenant_id)
        original_digest = source.image_hash
        db.commit()

    def replace_source(*_args, **_kwargs):
        source_path.write_bytes(b"different bytes after inference")
        extraction = _ocr_result()[0]
        return [replace(extraction, result=replace(extraction.result, evidence={"input_sha256": original_digest}))]

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", replace_source)
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    background_task_worker.run_task(task_id, _payload(expense_id, predecessor))
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "failed" and task.error_code == "image_integrity_mismatch"
        assert task.result_summary_json is None
        assert db.get(Expense, expense_id).row_version == predecessor
        assert db.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 0
