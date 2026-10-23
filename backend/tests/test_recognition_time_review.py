"""Time evidence reaches real reads and the existing explicit edit command."""

import json
import re
from datetime import UTC, datetime
from html import unescape
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Expense, OcrFact
from app.schemas import ExpenseResponse
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from tests._runtime_protocol import negotiated_headers


def _seed(raw):
    with SessionLocal() as db:
        expense = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            created_at=datetime(2026, 1, 1, tzinfo=UTC))
        db.add(expense)
        db.flush()
        snapshot = ocr_fact_snapshot(OcrResult(raw_text=raw, confidence=None), expense=expense, timezone_name="Asia/Shanghai")
        fact = record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense.id,
            ocr_provider="manual_text", raw_text=raw, evidence_json=json.dumps(snapshot.evidence)))
        db.flush()
        fact_id = fact.public_id
        # An empty retry must not combine old text with evidence from a different extraction.
        record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense.id,
            ocr_provider="empty", raw_text=""))
        db.commit()
        return expense.id, fact_id


@pytest.mark.parametrize("manual_amount", [None, 2200])
def test_multi_transaction_image_keeps_event_identity_in_actual_review(client, web_client, identity, manual_amount):
    raw = ("支付成功\n商户：蓝湾餐厅\n支付金额：12.60元\n支付时间：2025-12-20 12:30\n"
        "支付成功\n商户：青松商店\n支付金额：12.60元\n支付时间：2025-12-21 08:20")
    with SessionLocal() as db:
        expense = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            amount_cents=manual_amount, home_currency_code="CNY", original_currency_code="CNY")
        db.add(expense)
        db.flush()
        apply_ocr_result_and_append_fact(db, expense=expense,
            result=OcrResult(raw_text=raw, confidence=0.9, amount_cents=1260, merchant="蓝湾餐厅", category="餐饮"),
            provider_name="manual_text")
        db.commit()
        expense_id, version = expense.id, expense.row_version
        fact = db.query(OcrFact).filter_by(expense_id=expense_id).one()
        frozen_evidence = fact.evidence_json
        assert expense.amount_cents == manual_amount and expense.merchant is None
        assert expense.expense_time is None and expense.category == "其他"
        events = json.loads(frozen_evidence)["field_parse"]["events"]
        assert len(events) == 2 and not set(events[0]["candidate_ids"]).intersection(events[1]["candidate_ids"])

    response = client.get("/api/expenses/pending", headers=negotiated_headers(client, identity.app_headers))
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == expense_id)
    assert item["amount_cents"] == manual_amount and item["recognition_time"]["status"] == "ambiguous"
    assert item["recognition_notes"] == [
        "原件包含多笔交易；请先确定本次记录哪一笔，再核对该笔的金额、商户与时间。",
        "第1笔 · 支付金额：CNY 12.60", "第2笔 · 支付金额：CNY 12.60"]
    candidates = item["recognition_time"]["candidates"]
    assert [value["label"] for value in candidates] == ["图片 · 第1笔 · 支付时间", "图片 · 第2笔 · 支付时间"]
    assert candidates[0]["original_text"] != candidates[1]["original_text"]
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert all(note in page.text for note in item["recognition_notes"])
    assert all(value["label"] in page.text for value in candidates)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.amount_cents == manual_amount and expense.row_version == version
        assert db.query(OcrFact).filter_by(expense_id=expense_id).one().evidence_json == frozen_evidence


def test_api_date_only_choice_is_explicit_replayable_and_keeps_source_fact(client, identity):
    raw = "交易日期：2025-12-31\n打印时间：2026-01-01 12:30"
    expense_id, fact_id = _seed(raw)
    headers = negotiated_headers(client, identity.app_headers)
    response = client.get("/api/expenses/pending", headers=headers)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == expense_id)
    evidence = item["recognition_time"]
    assert evidence["evidence_public_id"] == fact_id and item["raw_text"] == raw
    day, printed = evidence["candidates"]
    assert day["local_value"] == "2025-12-31" and day["can_apply"]
    assert not printed["can_apply"] and printed["original_text"].startswith("打印时间")
    assert item["expense_time"] is None
    body = {"expected_row_version": item["row_version"], "time_input": {
        "precision": "date_only", "calendar_revision": 1, "user_local_date": day["local_value"]}}
    headers["Idempotency-Key"] = str(uuid4())
    saved = client.patch(f"/api/expenses/{expense_id}", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    replay = client.patch(f"/api/expenses/{expense_id}", headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    for value in (saved.json(), replay.json()):
        assert value["expense_time"] is None and value["accounting_time"]["precision"] == "date_only"
        assert value["accounting_time"]["user_local_date"] == "2025-12-31"
        assert value["amount_cents"] is None and value["status"] == "pending"
        assert value["recognition_time"] == evidence
    # A historic stored response does not grow a new field on replay/deserialization.
    new_fields = {"recognition_time", "recognition_notes"}
    old = {key: value for key, value in item.items() if key not in new_fields}
    assert not new_fields.intersection(ExpenseResponse.model_validate(old).model_dump(mode="json"))


@pytest.mark.parametrize("literal", ["12月31日23:59", "昨天23:59"])
def test_web_keeps_missing_image_date_unknown_without_a_capture_anchor(web_client, identity, literal):
    raw = f"交易时间：{literal}"
    expense_id, fact_id = _seed(raw)
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    choices = [json.loads(unescape(value)) for value in re.findall(r"data-recognized-time='([^']+)'", page.text)]
    assert not choices
    assert raw in page.text and "缺少完整日期" in page.text
    assert "2025-12-31T23:59" not in page.text
    assert f'data-fact-id="{fact_id}"' in page.text
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.expense_time is None and expense.row_version == 1
        assert expense.amount_cents is None and expense.status == "pending"


@pytest.mark.parametrize("manual_amount", [None, 2200])
def test_refund_amount_is_evidence_not_expense_and_review_preserves_manual_draft(
    client, web_client, identity, manual_amount,
):
    raw = "退款成功\n退款金额：25.00元"
    with SessionLocal() as db:
        expense = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            amount_cents=manual_amount, home_currency_code="CNY", original_currency_code="CNY")
        db.add(expense)
        db.flush()
        apply_ocr_result_and_append_fact(db, expense=expense,
            result=OcrResult(raw_text=raw, confidence=0.9, amount_cents=2500), provider_name="manual_text")
        db.commit()
        expense_id = expense.id
        assert expense.amount_cents == manual_amount
        fact = db.query(OcrFact).filter_by(expense_id=expense_id).one()
        assert fact.parsed_amount_cents is None and fact.raw_text == raw
        frozen_evidence = fact.evidence_json
        row_version = expense.row_version

    response = client.get("/api/expenses/pending", headers=negotiated_headers(client, identity.app_headers))
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == expense_id)
    assert item["amount_cents"] == manual_amount
    assert item["recognition_notes"] == ["原件显示退款，请核对类型与金额，不要当作新增消费。", "退款：CNY 25.00"]
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "data-recognition-amount-notes" in page.text
    assert all(note in page.text for note in item["recognition_notes"])
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.amount_cents == manual_amount and expense.status == "pending"
        assert expense.row_version == row_version
        assert db.query(OcrFact).filter_by(expense_id=expense_id).one().evidence_json == frozen_evidence
