"""Real command replay and atomic source replacement for a selected OCR line."""

import io
import json
from copy import deepcopy

import pytest
from PIL import Image
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask, Expense, OcrFact
from app.services import background_task_worker
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_ocr_task_service import submit_expense_ocr_task
from app.services.expense_service import _enrich, _ocr, stage_pending_expense
from app.services.expense_service._ocr_facts import append_ocr_fact
from app.services.file_service import save_upload_bytes
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.ocr_region_service import merge_region_evidence
from app.services.ocr_service import OcrResult
from app.services.optimistic_concurrency import bump_row_version

pytestmark = pytest.mark.real_db


def _block(text, box):
    left, top, right, bottom = box
    return {"text": text, "confidence": 0.9, "box": [[left, top], [right, top], [right, bottom], [left, bottom]]}


@pytest.fixture
def region_input(identity, monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    saved = save_upload_bytes(buffer.getvalue(), tenant_id="owner", filename="region.png", content_type="image/png")
    with SessionLocal() as db:
        expense = stage_pending_expense(db, saved, "owner", source="网页上传")
        expense.original_currency_code = "CNY"
        db.flush()
        evidence = {"schema": "text-blocks/v1", "width": 120, "height": 80,
            "input_sha256": expense.image_hash, "coordinate_space": "exif-transposed-pixels",
            "identity": {"recipe_name": "baseline"},
            "blocks": [_block("商户：青禾超市", [0, 0, 80, 15]), _block("实付", [0, 30, 30, 45]),
                       _block("21", [70, 30, 90, 45])]}
        append_ocr_fact(db, expense=expense, result=OcrResult(raw_text="商户：青禾超市\n实付\n21",
            confidence=0.9, evidence=evidence), provider_name="rapidocr")
        db.commit()
        request = {"expense_id": expense.id, "tenant_id": "owner",
            "initiator_account_id": find_owner_account_id_for_ledger(db, ledger_id="owner"), "initiator_device_id": None,
            "expected_row_version": expense.row_version, "request_expected_row_version": expense.row_version,
            "idempotency_key": "region-command", "region": {"image_sha256": expense.image_hash, "box": [60, 25, 110, 50]}}
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *a, **kw: None)
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "rapidocr")
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *a: None)
    return request, evidence


def _retry(evidence, box):
    return {**deepcopy(evidence), "region": box, "blocks": [_block("216.75", box)],
            "identity": {"recipe_name": "region-small"}, "timings_ms": {"inference": 10}, "decoding": {"method": "original"}}


def test_region_replay_keeps_one_append_only_source_and_original_intent(region_input, monkeypatch):
    request, evidence = region_input
    calls = []

    def recognize(_path, digest, box):
        calls.append((digest, box))
        return _retry(evidence, box)

    monkeypatch.setattr("app.services.ocr_region_service.recognize_region_snapshot", recognize)
    with SessionLocal() as db:
        task = submit_expense_ocr_task(db, **request)
        task_id, public_id, payload = task.id, task.public_id, json.loads(task.input_payload_json)
        assert submit_expense_ocr_task(db, **request).public_id == public_id
        with pytest.raises(AppError) as caught:
            submit_expense_ocr_task(db, **{**request, "region": {**request["region"], "box": [50, 25, 110, 50]}})
        assert caught.value.error == "idempotency_key_reused"
    background_task_worker.run_task(task_id, payload)
    with SessionLocal() as db:
        assert db.get(BackgroundTask, task_id).status == "completed"
        facts = list(db.scalars(select(OcrFact).where(OcrFact.expense_id == request["expense_id"]).order_by(OcrFact.id)))
        assert [fact.raw_text for fact in facts] == ["商户：青禾超市\n实付\n21", "商户：青禾超市\n实付\n216.75"]
        current = json.loads(facts[-1].evidence_json)
        assert current["blocks"][:2] == evidence["blocks"][:2]
        assert current["regional_retry"]["base_evidence_public_id"] == facts[0].public_id
        assert current["regional_retry"]["previous_blocks"] == evidence["blocks"][2:]
        assert db.get(Expense, request["expense_id"]).status == "pending"
        assert submit_expense_ocr_task(db, **request).public_id == public_id
    assert calls == [(request["region"]["image_sha256"], request["region"]["box"])]


def test_edit_during_region_recognition_wins_and_no_new_fact_is_applied(region_input, monkeypatch):
    request, evidence = region_input

    def edit_while_computing(_path, _digest, box):
        with SessionLocal() as db:
            resolve_write_capability(db)
            expense = db.get(Expense, request["expense_id"])
            expense.merchant = "用户已核对商户"
            bump_row_version(expense)
            db.commit()
        return _retry(evidence, box)

    monkeypatch.setattr("app.services.ocr_region_service.recognize_region_snapshot", edit_while_computing)
    with SessionLocal() as db:
        task = submit_expense_ocr_task(db, **request)
        task_id, payload = task.id, json.loads(task.input_payload_json)
    background_task_worker.run_task(task_id, payload)
    with SessionLocal() as db:
        assert json.loads(db.get(BackgroundTask, task_id).result_summary_json)["outcome"] == "conflict"
        assert db.get(Expense, request["expense_id"]).merchant == "用户已核对商户"
        assert len(list(db.scalars(select(OcrFact).where(OcrFact.expense_id == request["expense_id"])))) == 1


def test_partial_or_multiple_lines_cannot_erase_unselected_evidence(region_input):
    request, evidence = region_input
    before = deepcopy(evidence)
    for box, error in [([80, 25, 110, 50], "ocr_region_incomplete"), ([0, 0, 120, 60], "ocr_region_invalid")]:
        with pytest.raises(AppError) as caught:
            merge_region_evidence(evidence, _retry(evidence, box), {**request["region"], "box": box})
        assert caught.value.error == error
        assert evidence == before
