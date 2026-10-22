"""Old Android local-reference retry keeps its original fingerprint and version chain."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, BackgroundTask, Expense, OcrFact
from app.services import background_task_worker, pending_fx_task_service
from app.services.expense_service import _ocr
from app.services.fx_rate_provider import EcbDailyRates
from app.services.idempotency import fingerprint_request
from app.services.ocr_service import OcrResult

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize("lose_apply_ack", [False, True])
@pytest.mark.parametrize("complete_fx_after_ack", [False, True])
def test_original_local_retry_acknowledges_applied_version_before_following_outbox_write(
    client, identity, monkeypatch, lose_apply_ack, complete_fx_after_ack,
):
    # Keep the independent FX writer controlled; a later FX commit is a real
    # OCC conflict, not a replay of the OCR command or an unapplied OCR result.
    fx_settings = SimpleNamespace(fx_rate_auto_sync_enabled=False)
    monkeypatch.setattr(pending_fx_task_service, "get_settings", lambda: fx_settings)
    creation = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": "original-ocr-chain", "home_currency_code": "CNY", "original_currency": "JPY",
        "original_amount": "300", "merchant": "用户原填写", "category": "餐饮",
        "expense_time": "2026-05-05T00:00:00Z"})
    assert creation.status_code == 200 and creation.json()["status"] == "pending"
    expense_id, predecessor = creation.json()["id"], creation.json()["row_version"]
    calls = []
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    monkeypatch.setattr(_ocr, "extract_ocr_result", lambda expense: calls.append(expense.id)
        or OcrResult(raw_text="controlled suggestion", confidence=None))
    path = "/api/expenses/local:original-ocr-chain"
    headers = {**identity.app_headers, "Idempotency-Key": "old-device-ocr-key"}
    original_commit, lost_ack = Session.commit, []

    def commit_then_lose_ack(db):
        applying = any(isinstance(row, BackgroundTask) and row.task_type == "expense_ocr_retry"
                       and row.result_summary_json is not None for row in db.identity_map.values())
        if lose_apply_ack and applying and not lost_ack:
            original_commit(db)
            # A different connection observes the legacy receipt with the fact,
            # before the task terminal update or HTTP response can succeed.
            with SessionLocal() as observer:
                task = observer.scalar(select(BackgroundTask).where(
                    BackgroundTask.source_expense_id == expense_id,
                    BackgroundTask.task_type == "expense_ocr_retry"))
                assert task.status == "running" and task.result_summary_json is not None
                claim = observer.scalar(select(ApiIdempotencyKey).where(
                    ApiIdempotencyKey.idempotency_key == "old-device-ocr-key"))
                assert (claim.status, claim.resource_type, claim.resource_id) == (
                    "succeeded", "expense", str(expense_id))
                assert observer.get(Expense, expense_id).row_version == predecessor + 1
                assert observer.scalar(select(func.count()).select_from(OcrFact).where(
                    OcrFact.expense_id == expense_id)) == 1
            lost_ack.append(True)
            raise SQLAlchemyError("synthetic lost apply commit acknowledgement")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", commit_then_lose_ack)
    accepted = client.post(path + "/ocr/retry", headers=headers, json={"expected_row_version": 0})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["id"] == expense_id
    version = accepted.json()["row_version"]
    assert version == predecessor + 1 and accepted.json()["status"] == "pending"
    if complete_fx_after_ack:
        fx_settings.fx_rate_auto_sync_enabled = True
        monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference", lambda _: EcbDailyRates(
            date(2026, 5, 5), {"EUR": Decimal(1), "JPY": Decimal(150), "CNY": Decimal(7)}))
        with SessionLocal() as db:
            ocr_task = db.scalar(select(BackgroundTask).where(BackgroundTask.task_type == "expense_ocr_retry"))
            fx = pending_fx_task_service.prepare_pending_expense_fx(db, expense=db.get(Expense, expense_id),
                initiator_account_id=ocr_task.initiated_by_account_id,
                initiator_device_id=ocr_task.initiated_by_device_id)
            db.commit()
            fx_id, fx_payload = fx.task_id, fx.payload
        background_task_worker.run_task(fx_id, fx_payload)
        with SessionLocal() as db:
            assert db.get(BackgroundTask, fx_id).status == "completed"
            assert db.get(Expense, expense_id).row_version == version + 1
    # The next Outbox command depends on the completed OCR response's token.
    edited = client.patch(path, headers={**identity.app_headers, "Idempotency-Key": "next-edit-key"},
        json={"expected_row_version": version, "merchant": "另一端核对后的现商家"})
    if complete_fx_after_ack:
        assert edited.status_code == 409 and edited.json()["error"] == "state_conflict"
        refreshed = client.post(path + "/ocr/retry", headers=headers, json={"expected_row_version": 0})
        assert refreshed.status_code == 200 and refreshed.json()["row_version"] == version + 1
        assert refreshed.json()["merchant"] == "用户原填写"
        edited = client.patch(path, headers={**identity.app_headers, "Idempotency-Key": "next-edit-key"},
            json={"expected_row_version": refreshed.json()["row_version"], "merchant": "另一端核对后的现商家"})
    assert edited.status_code == 200, edited.text
    replay = client.post(path + "/ocr/retry", headers=headers, json={"expected_row_version": 0})
    assert replay.status_code == 200, replay.text
    assert replay.json()["row_version"] == edited.json()["row_version"]
    assert replay.json()["merchant"] == "另一端核对后的现商家"
    assert calls == [expense_id]
    assert lost_ack == ([True] if lose_apply_ack else [])
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "old-device-ocr-key"))
        assert claim.status == "succeeded" and claim.resource_type == "expense"
        assert claim.request_fingerprint == fingerprint_request(operation="retry_ocr", target_id=str(expense_id),
            body={}, expected_row_version=0)
        assert db.scalar(select(func.count()).select_from(OcrFact).where(OcrFact.expense_id == expense_id)) == 1
