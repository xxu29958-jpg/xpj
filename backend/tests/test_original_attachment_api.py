"""Real HTTP/PostgreSQL qualification for original continuation (cloud lane)."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.attachment_cleanup_contract import CleanupFile, CleanupRequest
from app.database import SessionLocal
from app.models import Expense, Ledger, LedgerMember
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES

pytestmark = pytest.mark.real_db


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


def test_reviewed_legacy_baseline_and_original_receipt_survive_later_file_damage(client, identity):
    expense_id, saved, source = _bill(client, identity, legacy=True)
    path = f"/api/expenses/{expense_id}/original"
    before = _financial_snapshot(expense_id)
    health = client.get(path, headers=identity.app_headers)
    assert health.status_code == 200, health.text
    assert health.json()["state"] == "unverified"
    payload = {"expected_row_version": health.json()["row_version"], "reviewed_sha256": health.json()["observed_sha256"]}
    headers = {**identity.app_headers, "Idempotency-Key": "original-verify"}
    accepted = client.post(path + "/verify", headers=headers, json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["sha256"] == saved.image_hash
    assert client.get(path, headers=identity.app_headers).json()["state"] == "verified"
    source.write_bytes(b"changed after acceptance")
    assert client.get(path, headers=identity.app_headers).json()["state"] == "corrupt"
    assert client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers).status_code == 409
    replay = client.post(path + "/verify", headers=headers, json=payload)
    assert replay.status_code == 200 and replay.json() == accepted.json()
    assert _financial_snapshot(expense_id) == before


def test_missing_original_is_replenished_on_same_bill_with_occ_and_stable_receipt(client, identity):
    expense_id, saved, source = _bill(client, identity)
    path = f"/api/expenses/{expense_id}/original"
    before = _financial_snapshot(expense_id)
    source.unlink()
    health = client.get(path, headers=identity.app_headers).json()
    assert health["state"] == "missing"
    query = {"expected_row_version": health["row_version"], "expected_sha256": saved.image_hash}
    headers = {**identity.app_headers, "Idempotency-Key": "original-replenish"}
    files = {"file": ("receipt.png", PNG_BYTES, "image/png")}
    accepted = client.post(path + "/replenish", headers=headers, params=query, files=files)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["expense_id"] == expense_id
    assert client.get(path, headers=identity.app_headers).json()["state"] == "verified"
    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 200 and image.content == PNG_BYTES
    replay = client.post(path + "/replenish", headers=headers, params=query, files=files)
    assert replay.status_code == 200 and replay.json() == accepted.json()
    stale = client.post(path + "/replenish", headers={**headers, "Idempotency-Key": "new-stale-attempt"},
        params=query, files=files)
    assert stale.status_code == 409 and stale.json()["error"] == "state_conflict"
    assert _financial_snapshot(expense_id) == before


def test_original_queries_are_ledger_scoped_and_mutations_require_writer(client, identity):
    expense_id, _, _ = _bill(client, identity, legacy=True)
    path = f"/api/expenses/{expense_id}/original"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=identity.gray_app_headers).status_code == 404
    health = client.get(path, headers=identity.app_headers).json()
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
            LedgerMember.account_id == ledger.owner_account_id))
        member.role = "viewer"
        db.commit()
    assert client.get(path, headers=identity.app_headers).status_code == 200
    response = client.post(path + "/verify", headers={**identity.app_headers, "Idempotency-Key": "viewer-verification"},
        json={"expected_row_version": health["row_version"], "reviewed_sha256": health["observed_sha256"]})
    assert response.status_code == 403


def test_cancel_settles_prior_deletion_and_preserves_remaining_file(client, identity):
    expense_id, _, source = _bill(client, identity)
    thumbnail = save_upload_bytes(PNG_BYTES, tenant_id="owner", filename="thumbnail.png", content_type="image/png")
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        expense.thumbnail_path = thumbnail.relative_path
        request = CleanupRequest(request_id=uuid4(), reason="after_confirm", requested_at=now_utc(),
            image=CleanupFile(reference=expense.image_path), thumbnail=CleanupFile(reference=thumbnail.relative_path))
        expense.attachment_cleanup_request = request.model_dump(mode="json")
        db.commit()
    source.unlink()  # Accepted cleanup lost its result update before this command.
    path = f"/api/expenses/{expense_id}/original"
    health = client.get(path, headers=identity.app_headers).json()
    headers = {**identity.app_headers, "Idempotency-Key": "cancel-accepted-cleanup"}
    payload = {"expected_row_version": health["row_version"], "request_id": str(request.request_id)}
    response = client.post(path + "/cleanup/cancel", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["cleanup_pending"] is False
    after = client.get(path, headers=identity.app_headers).json()
    assert after["state"] == "cleaned" and after["cleanup"] is None
    assert resolve_upload_path_for_tenant(thumbnail.relative_path, "owner").is_file()
    assert client.post(path + "/cleanup/cancel", headers=headers, json=payload).json() == response.json()
