"""Notification-only consumers and source history survive unrelated image changes."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, PaymentCapture
from tests._runtime_protocol import negotiated_headers
from tests.test_notification_field_review import _save
from tests.test_recognition_choice import _choose


def _new(client, identity, day, *, evidence=True):
    payload = {"notification_key": str(uuid4()), "source": "alipay", "captured_at": "2026-10-23T04:00:00Z",
        "original_currency": "CNY", "original_amount_minor": 1800, "merchant": "海棠咖吽", "suggested_kind": "expense",
        "parser_version": "transaction-evidence-v4", "candidates": [],
        "field_evidence": {"fragments": [{"field": "text", "literal": "商户：海棠咖吽"},
            {"field": "text", "literal": "支付金额：18.00元"}], "truncated": False},
        "time_evidence": {"source_timezone": "Asia/Shanghai", "truncated": False, "fragments": [
            {"field": "text", "label": label, "literal": f"2026-10-{day:02d} {clock}"}
            for label, clock in (("支付时间", "12:30"), ("消费时间", "12:20"))]}}
    response = client.post("/api/payment-captures", headers=identity.app_headers,
        json=payload if evidence else {**payload, "field_evidence": None, "time_evidence": None, "parser_version": "legacy"})
    assert response.status_code == 201, response.text
    return response.json(), payload


def _learn(client, identity, expense_id, kind):
    if kind == "field":
        current = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
        choice = next(c for c in current["recognition_fields"] if c["field"] == "merchant")
        _save(client, negotiated_headers(client, identity.app_headers), expense_id, choice, "海棠咖啡", "original_correction")
    else:
        response, *_ = _choose(client, identity, expense_id, index=1)
        assert response.status_code == 200, response.text


def _has_memory(row, kind):
    if kind == "field":
        return any(c["field"] == "merchant" and c["value"] == "海棠咖啡" for c in row["recognition_fields"])
    return "你曾" in row["recognition_time"]["candidates"][0]["explanation"]


def test_notification_only_pending_list_keeps_fields_and_personal_time_ranking(client, identity):
    first, _ = _new(client, identity, 18)
    for kind in ("field", "time"):
        _learn(client, identity, first["expense_id"], kind)
    later, _ = _new(client, identity, 19)
    detail = client.get(f"/api/expenses/{later['expense_id']}", headers=identity.app_headers).json()
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.text
    listed = next(row for row in pending.json() if row["id"] == later["expense_id"])
    assert listed["raw_text"] is None
    for kind in ("field", "time"):
        assert _has_memory(detail, kind)
        assert _has_memory(listed, kind), kind


@pytest.mark.parametrize("kind", ["field", "time"])
def test_adding_an_image_does_not_retire_an_unchanged_notification_choice(client, identity, kind):
    first, _ = _new(client, identity, 18)
    _learn(client, identity, first["expense_id"], kind)
    later, _ = _new(client, identity, 19)
    url = f"/api/expenses/{later['expense_id']}"
    assert _has_memory(client.get(url, headers=identity.app_headers).json(), kind)
    with SessionLocal() as db:
        source = db.get(Expense, first["expense_id"])
        source.image_hash = "a" * 64
        source.row_version += 1
        db.commit()
    assert _has_memory(client.get(url, headers=identity.app_headers).json(), kind)


@pytest.mark.parametrize("kind", ["field", "time"])
def test_backfilled_fragments_keep_their_parser_version_for_later_cases(client, identity, kind):
    old, payload = _new(client, identity, 18, evidence=False)
    with SessionLocal() as db:
        capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == old["public_id"]))
        capture.identity_hash = None
        db.commit()
    backfilled = client.post("/api/payment-captures", headers=identity.app_headers, json=payload)
    assert backfilled.status_code == 201, backfilled.text
    assert backfilled.json()["public_id"] == old["public_id"]
    assert backfilled.json()["captured_at"] == old["captured_at"]
    _learn(client, identity, old["expense_id"], kind)
    later, _ = _new(client, identity, 19)
    row = client.get(f"/api/expenses/{later['expense_id']}", headers=identity.app_headers).json()
    assert _has_memory(row, kind)
