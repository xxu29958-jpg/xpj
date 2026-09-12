"""Actual capture/edit entries stage the same original conversion with their real actor."""

import json
from uuid import uuid4

import pytest
from api_contract_helpers import upload_png
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BackgroundTask
from app.services.identity_service import authenticate_session_token


def _assert_original_task(bill, identity):
    assert (bill["status"], bill["fx_status"], bill["amount_cents"]) == ("pending", "pending", None)
    assert bill["original_amount_minor"] == 12345 and bill["original_currency_code"] == "USD"
    assert bill["fx_task"]["task_type"] == "expense_fx" and bill["fx_task"]["status"] == "queued"
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.app_token, {"app"})
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == bill["fx_task"]["public_id"]))
        assert (task.tenant_id, task.initiated_by_account_id, task.initiated_by_device_id) == (
            auth.tenant_id, auth.account_id, auth.device_id)
        original = json.loads(task.input_payload_json)
        assert (task.source_expense_id, original["expense_id"], original["expected_row_version"],
            original["rate_date"], original["original_amount_minor"]) == (
            bill["id"], bill["id"], bill["row_version"], "2026-05-04", 12345)


@pytest.mark.parametrize("entry", ["manual", "notification-drafts"])
def test_explicit_foreign_capture_stages_once_and_original_replay_does_not_duplicate(client, identity, entry):
    payload = {"original_currency_code": "USD", "original_amount_minor": 12345,
        "spent_at": "2026-05-04T04:00:00Z", "merchant": "Foreign cafe", "category": "餐饮"}
    if entry == "manual":
        payload.update(home_currency_code="CNY", client_ref=str(uuid4()))
    else:
        payload.update(source="wechat", notification_key=str(uuid4()))
    response = client.post(f"/api/expenses/{entry}", headers=identity.app_headers, json=payload)
    assert response.status_code == 200, response.text
    _assert_original_task(response.json(), identity)
    replay = client.post(f"/api/expenses/{entry}", headers=identity.app_headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == response.json()["id"]
    assert replay.json()["fx_task"]["public_id"] == response.json()["fx_task"]["public_id"]
    with SessionLocal() as db:
        tasks = list(db.scalars(select(BackgroundTask).where(
            BackgroundTask.tenant_id == "owner", BackgroundTask.task_type == "expense_fx",
            BackgroundTask.source_expense_id == response.json()["id"])))
        assert len(tasks) == 1


def test_captured_bill_edit_then_text_recognition_keeps_original_money_and_conversion_entry(client, identity):
    expense_id = upload_png(client, identity=identity)
    url = f"/api/expenses/{expense_id}"
    first = client.get(url, headers=identity.app_headers).json()
    payload = {"expected_row_version": first["row_version"], "original_currency_code": "USD",
        "original_amount_minor": 12345, "spent_at": "2026-05-04T04:00:00Z", "category": "餐饮"}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    edited = client.patch(url, headers=headers, json=payload)
    assert edited.status_code == 200, edited.text
    _assert_original_task(edited.json(), identity)
    replay = client.patch(url, headers=headers, json=payload)
    assert replay.status_code == 200 and replay.json()["fx_task"] == edited.json()["fx_task"]
    recognized = client.post(f"{url}/recognize-text", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": edited.json()["row_version"], "raw_text": "示例咖啡店"})
    assert recognized.status_code == 200, recognized.text
    _assert_original_task(recognized.json(), identity)
    assert recognized.json()["fx_task"]["public_id"] != edited.json()["fx_task"]["public_id"]
