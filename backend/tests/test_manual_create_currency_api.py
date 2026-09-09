"""Public manual commands preserve captured money across a default change."""

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuthToken, Expense
from app.schemas import ExpenseManualCreateRequest
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_query import local_ref_storage_key
from app.services.expense_service._create import _manual_request_fingerprint
from app.services.identity_service import hash_secret


def test_manual_create_and_replay_preserve_captured_jpy_under_current_cny(client, identity):
    body = {"home_currency_code": "JPY", "original_currency": "JPY", "original_amount": "12",
        "client_ref": "captured-jpy", "category": "餐饮"}
    with SessionLocal() as db:
        assert resolve_write_capability(db).home_currency_code == "CNY"
    accepted = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert accepted.status_code == 200, accepted.text
    replay = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert replay.status_code == 200 and replay.json()["id"] == accepted.json()["id"]
    result = accepted.json()
    assert (result["home_currency"], result["original_currency_code"],
        result["original_amount_minor"], result["amount_cents"]) == ("JPY", "JPY", 12, 12)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 1
        row = db.get(Expense, result["id"])
        assert (row.home_currency_code, row.original_currency_code,
            row.original_amount_minor, row.amount_cents) == ("JPY", "JPY", 12, 12)


def test_unaccepted_legacy_bare_money_is_refused_but_accepted_original_key_can_recover(client, identity):
    body = {"amount_cents": 12, "client_ref": "legacy-amount", "category": "餐饮"}
    refused = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "manual_currency_context_required"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token)))
        resolve_write_capability(db)
        row = Expense(tenant_id="owner", home_currency_code="JPY", original_currency_code="JPY",
            amount_cents=12, original_amount_minor=12, category="餐饮", source="手动记账", status="confirmed",
            draft_idempotency_key=local_ref_storage_key(token.device_id, body["client_ref"]),
            draft_request_fingerprint=_manual_request_fingerprint(ExpenseManualCreateRequest(**body)))
        db.add(row)
        db.commit()
        saved_id = row.id
    recovered = client.post("/api/expenses/manual", json=body, headers=identity.app_headers)
    assert recovered.status_code == 200, recovered.text
    assert (recovered.json()["id"], recovered.json()["home_currency"], recovered.json()["amount_cents"]) == (saved_id, "JPY", 12)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 1
