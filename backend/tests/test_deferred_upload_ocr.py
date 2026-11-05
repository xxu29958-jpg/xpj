from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from uuid import uuid4

import pytest
from api_contract_helpers import confirm_expense_api, reject_expense_api
from sqlalchemy import select

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.models import BackgroundTask, Expense, OcrFact
from app.recognition_config import resolve_recognition_config
from app.services.background_task_recovery_service import resume_due_ocr_tasks
from app.services.deferred_upload_ocr import queue_skipped_uploads
from app.services.ocr_service import OcrResult
from app.services.ocr_service._providers import RapidOcrProvider
from app.services.runtime_settings_store import RecognitionSettingsProjection
from tests._infra.assets import PNG_BYTES


def test_fresh_install_uses_local_ocr_and_respects_saved_opt_out(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.delenv("OCR_AUTO_RUN", raising=False)
    fresh = resolve_recognition_config(None)
    assert (fresh.ocr_provider, fresh.ocr_auto_run) == ("rapidocr", True)
    off = RecognitionSettingsProjection(**{**asdict(fresh), "ocr_auto_run": False})
    assert resolve_recognition_config(off).ocr_auto_run is False
    monkeypatch.setenv("OCR_PROVIDER", "empty")
    assert resolve_recognition_config(None).ocr_auto_run is False


@pytest.mark.real_db
def test_skipped_upload_and_old_receipt_catch_up_once_without_reupload(client, identity, monkeypatch):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    monkeypatch.setenv("OCR_PROVIDER", "empty")
    reset_settings_cache()

    def upload(key):
        response = client.post("/api/app/upload-screenshot", content=PNG_BYTES,
            headers={**identity.app_headers, "Content-Type": "image/png", "Idempotency-Key": key})
        assert response.status_code == 200, response.text
        return response.json()

    keys = [str(uuid4()) for _ in range(4)]
    first, legacy, rejected, confirmed = [upload(key) for key in keys]
    records = (first, legacy, rejected, confirmed)
    with SessionLocal.begin() as db:
        original = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == legacy["enrichment_task_public_id"]))
        old_summary = json.loads(original.result_summary_json)
        assert old_summary.pop("ocr_notice") == "auto_ocr_disabled"
        assert not old_summary.get("ocr_attempts")
        original.result_summary_json = json.dumps(old_summary)
        old_receipt = original.result_summary_json
    projected = client.get(f"/api/tasks/{legacy['enrichment_task_public_id']}", headers=identity.app_headers)
    assert projected.json()["result_summary"]["ocr_notice"] == "auto_ocr_disabled"
    current = client.get(f"/api/expenses/{first['id']}", headers=identity.app_headers).json()
    edit = client.patch(f"/api/expenses/{first['id']}", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": current["row_version"], "merchant": "人工核对的商户"})
    assert edit.status_code == 200, edit.text
    assert reject_expense_api(client, rejected["id"], headers=identity.app_headers).status_code == 200
    url = f"/api/expenses/{confirmed['id']}"
    basis = client.get(url, headers=identity.app_headers).json()["row_version"]
    ready = client.patch(url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
                         json={"expected_row_version": basis, "amount_cents": 777, "category": "餐饮"})
    assert ready.status_code == 200, ready.text
    assert confirm_expense_api(client, confirmed["id"], headers=identity.app_headers).status_code == 200
    queue_skipped_uploads(0)
    with SessionLocal() as db:
        assert len(list(db.scalars(select(BackgroundTask).where(BackgroundTask.task_type == "expense_enrichment")))) == 4

    monkeypatch.delenv("OCR_PROVIDER")
    monkeypatch.delenv("OCR_AUTO_RUN", raising=False)
    reset_settings_cache()
    monkeypatch.setattr(RapidOcrProvider, "extract", lambda *_args, **_kw:
                        OcrResult("商户：测试超市\n实付：12.34元", 0.99))
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(queue_skipped_uploads, [0, 0]))
        # A fresh scheduler can discover the committed continuations after restart.
        resume_due_ocr_tasks()
        queue_skipped_uploads(0)
        with SessionLocal() as db:
            for receipt in records:
                tasks = list(db.scalars(select(BackgroundTask).where(
                    BackgroundTask.source_expense_id == receipt["id"], BackgroundTask.task_type == "expense_enrichment",
                ).order_by(BackgroundTask.id)))
                ineligible = receipt in (rejected, confirmed)
                assert len(tasks) == (1 if ineligible else 2)
                assert all(task.status == "completed" for task in tasks)
                facts = list(db.scalars(select(OcrFact).where(OcrFact.expense_id == receipt["id"])))
                assert [fact.ocr_provider for fact in facts] == ([] if ineligible else ["rapidocr"])
                if receipt == legacy:
                    assert tasks[0].result_summary_json == old_receipt
                    assert db.get(Expense, legacy["id"]).amount_cents == 1234
            assert db.get(Expense, first["id"]).merchant == "人工核对的商户"
            assert db.get(Expense, confirmed["id"]).amount_cents == 777
        assert upload(keys[1]) == legacy
    finally:
        reset_settings_cache()
