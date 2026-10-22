"""Delayed notifications retain immutable time evidence and require a real edit."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PaymentCapture, Repayment
from app.schemas import RepaymentDraftResponse
from app.schemas.payment_capture import PaymentCaptureResponse
from app.services.notification_time_service import notification_times_for_expenses
from tests._runtime_protocol import negotiated_headers


def _capture(kind="expense"):
    return {"notification_key": str(uuid4()), "source": "alipay", "captured_at": "2026-01-01T02:00:01Z",
        "original_currency": "CNY", "original_amount_minor": 2500, "merchant": "原商家", "suggested_kind": kind,
        "parser_version": "transaction-evidence-v3", "candidates": [], "time_evidence": {
            "source_timezone": "Asia/Shanghai", "truncated": False, "fragments": [
                {"field": "text", "label": "交易时间", "literal": "12月31日23:59"},
                {"field": "text", "label": "接收时间", "literal": "2026-01-01 10:00"}]}}


def test_delivery_replay_keeps_original_evidence_and_expense_choice_is_explicit(client, identity):
    payload = _capture()
    response = client.post("/api/payment-captures", headers=identity.app_headers, json=payload)
    assert response.status_code == 201, response.json()
    original = response.json()
    old = {key: value for key, value in original.items() if key != "recognition_time"}
    assert "recognition_time" not in PaymentCaptureResponse.model_validate(old).model_dump(mode="json")
    evidence = original["recognition_time"]
    assert evidence["source"] == "notification" and evidence["evidence_public_id"] == original["public_id"]
    transaction, delivery = evidence["candidates"]
    assert transaction["local_value"] == "2025-12-31T23:59" and transaction["can_apply"]
    assert "缺少年份" in transaction["explanation"] and "手机设置" in transaction["explanation"]
    assert not delivery["can_apply"]
    payload["captured_at"] = "2027-01-01T02:00:01Z"
    payload["time_evidence"]["source_timezone"] = "America/New_York"
    replay = client.post("/api/payment-captures", headers=identity.app_headers, json=payload)
    assert replay.status_code == 201 and replay.json() == original
    url = f"/api/expenses/{original['expense_id']}"
    current = client.get(url, headers=identity.app_headers).json()
    assert current["expense_time"] is None and current["recognition_time"] == evidence
    assert current["raw_text"] is None  # This is notification evidence, not an invented OCR fact.
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    body = {"expected_row_version": current["row_version"], "merchant": "人工商家", "time_input": {
        "precision": "date_only", "calendar_revision": current["accounting_time"]["calendar_revision"],
        "user_local_date": transaction["local_value"].split("T")[0]}}
    edited = client.patch(url, headers=headers, json=body)
    assert edited.status_code == 200, edited.json()
    assert client.patch(url, headers=headers, json=body).json() == edited.json()
    saved = client.get(url, headers=identity.app_headers).json()
    assert saved["expense_time"] is None and saved["accounting_time"]["user_local_date"] == "2025-12-31"
    assert saved["recognition_time"] == evidence and saved["merchant"] == "人工商家"
    assert saved["original_amount_minor"] == 2500 and saved["status"] == "pending"
    assert client.get(f"/api/payment-captures/{original['public_id']}", headers=identity.gray_app_headers).status_code == 404
    with SessionLocal() as db:
        capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == original["public_id"]))
        assert notification_times_for_expenses(db, tenant_id="owner", actor_account_id=capture.actor_account_id + 1000,
            expense_public_ids=[capture.expense_public_id]) == {}
        assert capture.time_evidence["input"]["source_timezone"] == "Asia/Shanghai"


@pytest.mark.parametrize("kind", ["expense", "repayment"])
def test_identity_backfill_keeps_new_time_evidence_and_original_delivery(client, identity, kind):
    payload = _capture(kind)
    legacy = client.post("/api/payment-captures", headers=identity.app_headers,
        json={**payload, "time_evidence": None}).json()
    with SessionLocal() as db:
        capture = db.scalar(select(PaymentCapture).where(PaymentCapture.public_id == legacy["public_id"]))
        capture.identity_hash = None  # Historical draft materialized before notification identity was available.
        db.commit()
    if kind == "expense":
        payload["captured_at"] = "2027-01-01T02:00:01Z"
    response = client.post("/api/payment-captures", headers=identity.app_headers, json=payload)
    assert response.status_code == 201, response.json()
    restored = response.json()
    assert restored["public_id"] == legacy["public_id"]
    assert restored["captured_at"] == legacy["captured_at"]
    assert restored["original_amount_minor"] == legacy["original_amount_minor"]
    assert restored["recognition_time"]["candidates"][0]["local_value"] == "2025-12-31T23:59"
    payload["time_evidence"]["fragments"][0]["literal"] = "2026-02-03 08:00"
    assert client.post("/api/payment-captures", headers=identity.app_headers, json=payload).json() == restored
    with SessionLocal() as db:
        assert len(list(db.scalars(select(PaymentCapture)))) == 1


def test_printed_ocr_time_does_not_hide_actionable_notification_time(web_client, identity):
    from fastapi.testclient import TestClient

    from app.routes.web_auth import PAIRING_ATTEMPT_COOKIE_NAME, SESSION_COOKIE_NAME

    created = web_client.post("/api/payment-captures", headers=identity.app_headers, json=_capture()).json()
    url = f"/api/expenses/{created['expense_id']}"
    before = web_client.get(url, headers=identity.app_headers).json()
    headers = negotiated_headers(web_client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    raw = "打印时间：2026-01-01 09:00"
    parsed = web_client.post(url + "/recognize-text", headers=headers,
        json={"expected_row_version": before["row_version"], "raw_text": raw})
    assert parsed.status_code == 200, parsed.json()
    current = web_client.get(url, headers=identity.app_headers).json()
    assert current["recognition_time"] == created["recognition_time"]
    assert current["raw_text"] == raw and current["expense_time"] is None
    assert current["original_amount_minor"] == before["original_amount_minor"]
    login_form = web_client.get("/web/auth/login")
    connected = web_client.post("/web/auth/login", data={"pairing_code": identity.pairing_code,
        "device_name": "notification evidence review"}, follow_redirects=False,
        headers={"Cookie": f"{PAIRING_ATTEMPT_COOKIE_NAME}={login_form.cookies[PAIRING_ATTEMPT_COOKIE_NAME]}"})
    assert connected.status_code == 303
    # A real peer/host exercises cookie authentication; the legacy testserver
    # peer intentionally skips that middleware in the shared fixture.
    with TestClient(web_client.app, base_url="https://api.example.com", client=("203.0.113.20", 50002)) as browser:
        page = browser.get(f"/web/expenses/{created['expense_id']}/edit?ledger_id=owner",
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={connected.cookies[SESSION_COOKIE_NAME]}"})
    assert page.status_code == 200
    assert "2025-12-31T23:59" in page.text and f'data-fact-id="{created["public_id"]}"' in page.text


def test_repayment_date_review_and_replay_preserve_delivery_and_original_time_evidence(client, identity):
    response = client.post("/api/payment-captures", headers=identity.app_headers, json=_capture("repayment"))
    assert response.status_code == 201, response.json()
    capture = response.json()
    target = f"/api/repayment-drafts/{capture['repayment_public_id']}"
    draft = client.get(target, headers=identity.app_headers).json()
    old = {key: value for key, value in draft.items() if key != "recognition_time"}
    assert "recognition_time" not in RepaymentDraftResponse.model_validate(old).model_dump(mode="json")
    assert draft["accounting_time"]["precision"] == "unknown"
    assert draft["recognition_time"] == capture["recognition_time"]
    headers = negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())})
    debt = client.post("/api/debts", headers=headers, json={"home_currency_code": "CNY", "direction": "i_owe",
        "counterparty_type": "external", "counterparty_label": "花呗", "principal_amount_cents": 10000})
    assert debt.status_code == 201, debt.json()
    body = {"target_debt_public_id": debt.json()["public_id"], "expected_row_version": debt.json()["row_version"],
        "time_input": {"precision": "date_only", "calendar_revision": draft["accounting_time"]["calendar_revision"],
            "user_local_date": "2025-12-31"}}
    headers["Idempotency-Key"] = str(uuid4())
    accepted = client.post(target + "/confirm", headers=headers, json=body)
    assert accepted.status_code == 201, accepted.json()
    assert client.post(target + "/confirm", headers=headers, json=body).json() == accepted.json()
    assert accepted.json()["recognition_time"] == capture["recognition_time"]
    with SessionLocal() as db:
        fact = db.scalars(select(Repayment)).one()
        assert fact.paid_at is None and fact.accounting_time_snapshot["user_local_date"] == "2025-12-31"
        assert fact.amount_cents == 2500


@pytest.mark.parametrize("invalid", ["body", "naive"])
def test_capture_rejects_full_notification_body_or_unanchored_delivery_time(client, identity, invalid):
    payload = _capture()
    if invalid == "body":
        payload["time_evidence"]["fragments"][0]["literal"] = "2025-12-31 10:00 账户尾号1234"
    else:
        payload["captured_at"] = "2026-01-01T02:00:01"
    response = client.post("/api/payment-captures", headers=identity.app_headers, json=payload)
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(PaymentCapture)) is None
