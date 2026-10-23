"""A multi-card source can supply one coherent draft without teaching default roles."""
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Expense
from app.services.currency_binding_service import resolve_write_capability
from app.services.learning_service import OcrFactDraft, record_ocr_fact
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from tests._runtime_protocol import negotiated_headers


def event_material(*, ambiguous_amount=False, incomplete_time=False):
    first = "支付成功\n商户：海棠咖啡\n实付：18.00元\n支付时间：2026-10-20 12:30"
    amount = "实付：28.00元\n实付：29.00元" if ambiguous_amount else "实付：28.00元\n余额：900.00元"
    time = "支付时间：10月21日 09:20" if incomplete_time else "支付时间：2026-10-21 09:20"
    return first + "\n支付成功\n商户：青禾超市\n" + amount + "\n" + time


def seed_event_material(db, expense, *, ambiguous_amount=False, incomplete_time=False):
    raw = event_material(ambiguous_amount=ambiguous_amount, incomplete_time=incomplete_time)
    snapshot = ocr_fact_snapshot(OcrResult(raw_text=raw, confidence=None), expense=expense, timezone_name="Asia/Shanghai")
    record_ocr_fact(db, OcrFactDraft(tenant_id=expense.tenant_id, expense_id=expense.id,
        ocr_provider="manual_text", raw_text=raw, evidence_json=json.dumps(snapshot.evidence)))


@pytest.mark.parametrize("ambiguous_amount,incomplete_time", [(False, False), (True, False), (False, True)])
def test_event_recommendations_keep_fields_within_their_transaction_and_preserve_unknowns(
        client, identity, ambiguous_amount, incomplete_time):
    with SessionLocal() as db:
        resolve_write_capability(db)
        row = Expense(tenant_id="owner", source="camera", status="pending", category="其他",
            merchant="用户当前输入", amount_cents=1500, original_amount_minor=1500,
            original_currency_code="CNY", home_currency_code="CNY", image_hash=str(uuid4()),
            created_at=datetime(2026, 10, 22, tzinfo=UTC))
        db.add(row)
        db.flush()
        seed_event_material(db, row, ambiguous_amount=ambiguous_amount, incomplete_time=incomplete_time)
        db.commit()
        expense_id = row.id
    response = client.get(f"/api/expenses/{expense_id}", headers=negotiated_headers(client, identity.app_headers))
    assert response.status_code == 200, response.text
    data = response.json()
    fields, times = data["recognition_fields"], data["recognition_time"]["candidates"]
    merchant = next(item for item in fields if item["value"] == "青禾超市" and item["role"] == "merchant")
    event_id = merchant["event_id"]
    selected = [item for item in fields if item["event_id"] == event_id and item.get("event_selected")]
    assert {item["value"] for item in selected} == ({"青禾超市"} if ambiguous_amount else {"青禾超市", 2800})
    selected_times = [item for item in times if item.get("event_id") == event_id and item.get("event_selected")]
    assert len(selected_times) == (0 if incomplete_time else 1)
    if selected_times:
        assert selected_times[0]["local_value"] == "2026-10-21T09:20"
    assert data["merchant"] == "用户当前输入" and data["amount_cents"] == 1500
    assert data["status"] == "pending", "Reading evidence must not commit the proposed event"
