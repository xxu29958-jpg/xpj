"""Original-file preparation and delivery shared by its existing API/Web consumers."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from app.database import SessionLocal
from app.models import Expense
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import TEST_UPLOAD_DIR


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
