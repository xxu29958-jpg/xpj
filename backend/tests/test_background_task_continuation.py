"""Actual upload task outcomes must lead back to their original bill."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BackgroundTask, Expense, Ledger
from app.services import background_task_service, background_task_worker
from app.services.background_task_registry import TaskHandlerRegistry
from tests._infra.assets import PNG_BYTES

pytestmark = pytest.mark.real_db


def _failed_upload(client, monkeypatch, identity):
    def fail_recognition(db, task, payload):
        raise RuntimeError("recognition unavailable")

    registry = TaskHandlerRegistry({"expense_enrichment": fail_recognition})
    monkeypatch.setattr(
        background_task_service,
        "_submit_task",
        lambda task_id, payload, **_kwargs: background_task_worker.run_task(task_id, payload, registry),
    )
    response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.app_headers,
        files={"file": ("task-continuation.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_failed_upload_task_identifies_original_bill_without_changing_it(client, monkeypatch, *, identity):
    receipt = _failed_upload(client, monkeypatch, identity)
    task_url = f"/api/tasks/{receipt['enrichment_task_public_id']}"
    with SessionLocal() as db:
        expense = db.get(Expense, receipt["id"])
        original = (expense.public_id, expense.status, expense.row_version)
    for response in (
        client.get(task_url, headers=identity.app_headers),
        client.post(f"{task_url}/cancel", headers=identity.app_headers),
    ):
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "failed"
        assert body["source_expense_id"] == receipt["id"]
        assert body["result_summary"] is None
    listing = client.get("/api/tasks", headers=identity.app_headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"][0]["source_expense_id"] == receipt["id"]
    with SessionLocal() as db:
        expense = db.get(Expense, receipt["id"])
        assert (expense.public_id, expense.status, expense.row_version) == original


@pytest.mark.parametrize("payload", [None, {"expense_id": True, "tenant_id": "owner"},
    {"expense_id": 1, "tenant_id": "another-ledger"}, {"expense_id": 99999999, "tenant_id": "owner"}])
def test_task_with_unavailable_original_never_invents_a_bill_link(client, monkeypatch, payload, *, identity):
    receipt = _failed_upload(client, monkeypatch, identity)
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(
            BackgroundTask.public_id == receipt["enrichment_task_public_id"],
        ))
        task.input_payload_json = json.dumps(payload)
        db.commit()
    response = client.get(f"/api/tasks/{receipt['enrichment_task_public_id']}", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    assert response.json()["source_expense_id"] is None


@pytest.mark.parametrize("source_state", ["rejected", "other_ledger"])
def test_task_link_requires_the_original_bill_to_remain_accessible(client, monkeypatch, source_state, *, identity):
    receipt = _failed_upload(client, monkeypatch, identity)
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(
            BackgroundTask.public_id == receipt["enrichment_task_public_id"],
        ))
        expense = db.get(Expense, receipt["id"])
        if source_state == "other_ledger":
            db.add(Ledger(ledger_id="other_ledger", name="Other", owner_account_id=task.initiated_by_account_id))
            db.flush()
            expense.tenant_id = "other_ledger"
        else:
            expense.status = "rejected"
        db.commit()
    response = client.get(f"/api/tasks/{receipt['enrichment_task_public_id']}", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    assert response.json()["source_expense_id"] is None
