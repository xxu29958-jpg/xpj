"""Original-file preparation and delivery shared by its existing API/Web consumers."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.routes import web_originals
from app.services import background_task_worker, file_service, manual_expense_draft_presenter
from app.services.background_task_registry import TaskHandlerRegistry
from app.services.currency_binding_service import authorize_currency_metadata_write, resolve_write_capability
from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES, _camera_jpeg
from tests._infra.env import TEST_UPLOAD_DIR
from tests.web_expense_fact_test_support import confirmation_actor


def _bill(client, identity, *, legacy=False):
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json={
        "client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1234,
    })
    assert response.status_code == 200, response.text
    expense_id = response.json()["id"]
    saved = save_upload_bytes(PNG_BYTES, tenant_id="owner", filename="receipt.png", content_type="image/png")
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        expense.image_path = saved.relative_path
        expense.image_hash = "legacy" if legacy else saved.image_hash
        db.commit()
    return expense_id, saved, resolve_upload_path_for_tenant(saved.relative_path, "owner")


def _financial_snapshot(expense_id):
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        return {key: getattr(row, key) for key in ("id", "public_id", "amount_cents", "original_amount_minor",
            "original_currency_code", "home_currency_code", "expense_time", "accounting_date", "fact_revision")}


def _old_file(name: str, *, tenant_id="owner") -> Path:
    path = TEST_UPLOAD_DIR / tenant_id / "2026" / "01" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_BYTES)
    old = (now_utc() - timedelta(days=2)).timestamp()
    os.utime(path, (old, old))
    return path


def _assert_bill_and_unverified_original(response, expense_id, original_bytes):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(response.content)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["ledger_id"] == "owner" and manifest["records_complete"] is True
        assert manifest["restore_image"] is False and manifest["includes_client_unsubmitted_intents"] is False
        expenses = [json.loads(line) for line in package.read("records/expenses.jsonl").splitlines()]
        assert any(row["id"] == expense_id and row["amount_cents"] == 1234 for row in expenses)
        originals = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        original = next(row for row in originals if row["reference_id"] == f"expense:{expense_id}:current")
        assert original["state"] == "unverified"
        assert package.read(original["path"]) == original_bytes


SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
         "ledgerId": "owner", "deviceId": "browser"}


FACT_FIELDS = ("id", "public_id", "status", "merchant", "amount_cents", "original_amount_minor",
               "original_currency_code", "home_currency_code", "expense_time", "accounting_date", "fact_revision")


@pytest.fixture
def first_original_web(confirmation_store, confirmation_web, monkeypatch, tmp_path):
    client, options = confirmation_web
    client.app.include_router(web_originals.router)
    with confirmation_store() as db:
        auth = confirmation_actor(db)
    state = SimpleNamespace(auth=auth, original_auth=auth, options=options, client=client, session_factory=confirmation_store,
                            uploads=tmp_path / "uploads")

    def local(request: Request):
        request.state.web_session_auth = state.auth

    @client.app.exception_handler(AppError)
    async def error(_request, exc):
        return JSONResponse({"error": exc.error, "message": exc.message}, status_code=exc.status_code)

    client.app.dependency_overrides[web_originals.LocalOnly.dependency] = local
    monkeypatch.setattr(web_originals, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_originals, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: SCOPE)
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=state.uploads,
                                                                            max_upload_size_bytes=1024 * 1024, upload_min_free_bytes=0))
    with state.session_factory() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, 42)
        expense.source, expense.status, expense.fact_revision = "手动记账", "confirmed", 1
        db.commit()
    return state


def _attach(case, *, key="a" * 32, version=4, scope=SCOPE, data=None):
    return case.client.post("/web/expenses/42/original/attach", params={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": key, "expected_row_version": version},
        files={"file": ("camera.jpg", _camera_jpeg() if data is None else data, "image/jpeg")},
        headers={"Accept": "application/json"})


def _facts(case):
    with case.session_factory() as db:
        row = db.get(Expense, 42)
        return tuple(getattr(row, name) for name in FACT_FIELDS)


def _failed_upload(client, monkeypatch, headers):
    def fail_recognition(db, task, payload):
        raise RuntimeError("recognition unavailable")

    registry = TaskHandlerRegistry({"expense_enrichment": fail_recognition})
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, payload, **_kwargs: background_task_worker.run_task(task_id, payload, registry),
    )
    response = client.post(
        "/api/app/upload-screenshot",
        headers=headers,
        files={"file": ("task-continuation.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()
