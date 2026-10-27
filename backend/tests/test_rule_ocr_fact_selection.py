"""Bulk rule consumers use the same meaningful OCR evidence as single classification."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Expense
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.rule_service import classify_expense
from tests.test_rule_application_commands import _expense, _preview


@pytest.mark.parametrize("status", ["pending", "confirmed"])
@pytest.mark.parametrize("texts", [("餐饮原文", ""), ("", "餐饮原文"), ("旧原文", "餐饮原文")])
def test_bulk_preview_apply_and_replay_use_meaningful_fact(client, identity, status, texts):
    expense_id = _expense(status)
    created = client.post("/api/rules/categories",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"keyword": "餐饮原文", "category": "餐饮"})
    assert created.status_code == 200, created.text
    with SessionLocal() as db:
        for index, text in enumerate(texts):
            record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=expense_id,
                ocr_provider="local_llm", raw_text=text),
                now=datetime(2026, 5, 1, tzinfo=UTC) + timedelta(minutes=index))
        db.commit()
        expense = db.get(Expense, expense_id)
        assert classify_expense(db, expense).category == "餐饮"
        db.rollback()
    body = {**_preview(client, identity.app_headers, status), "reason": "确认按原文分类"}
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).category == "其他"
    path = f"/api/rules/apply-{status}"
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    applied = client.post(path, headers=headers, json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["changed_count"] == 1
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense.category == "餐饮" and expense.status == status
        version = expense.row_version
    assert client.post(path, headers=headers, json=body).json() == applied.json()
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).row_version == version
