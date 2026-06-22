"""Issue #65 slice 2 — ``resolve_expense`` central lookup + the audit lane.

``resolve_expense(db, tenant_id, ref, *, device_id=None)`` resolves a client-supplied
expense reference within ledger scope: a server id, or a device-local
``local:{client_ref}`` ref (through the ``draft_idempotency_key`` composite written by
``create_manual_expense``). It returns ``None`` on a miss (cross-tenant / cross-device /
unknown), and the device namespace is built inside the helper — callers pass the device,
never the composite key.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AuthToken
from app.services.expense_query import local_ref_storage_key, resolve_expense
from app.services.identity_service import hash_secret

_AUDIT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "_audit_expense_resolve.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("_audit_expense_resolve", _AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owner_device_id(identity) -> int:
    with SessionLocal() as db:
        tok = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(identity.app_token))
            .one()
        )
        return tok.device_id


def _create_manual(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "amount_cents": 1500,
        "merchant": "解析测试",
        "category": "餐饮",
        "expense_time": "2026-05-05T00:00:00Z",
    }
    body.update(overrides)
    resp = client.post("/api/expenses/manual", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_resolve_by_server_id(client: TestClient, *, identity) -> None:
    created = _create_manual(client, identity.app_headers)
    with SessionLocal() as db:
        resolved = resolve_expense(db, "owner", created["id"])
        assert resolved is not None
        assert resolved.id == created["id"]


def test_resolve_by_server_id_decimal_string(client: TestClient, *, identity) -> None:
    # The docstring advertises a decimal-string ref form (slice 3's route path params
    # arrive as strings). int(ref) must resolve it to the same row as the int id.
    created = _create_manual(client, identity.app_headers)
    with SessionLocal() as db:
        resolved = resolve_expense(db, "owner", str(created["id"]))
        assert resolved is not None
        assert resolved.id == created["id"]


def test_resolve_server_id_cross_tenant_miss(client: TestClient, *, identity) -> None:
    created = _create_manual(client, identity.app_headers)
    with SessionLocal() as db:
        # Same id, different ledger → no row in scope.
        assert resolve_expense(db, "tester_1", created["id"]) is None


def test_resolve_by_local_ref(client: TestClient, *, identity) -> None:
    device_id = _owner_device_id(identity)
    _create_manual(client, identity.app_headers, client_ref="resolve-ref")
    with SessionLocal() as db:
        resolved = resolve_expense(db, "owner", "local:resolve-ref", device_id=device_id)
        assert resolved is not None
        assert resolved.draft_idempotency_key == local_ref_storage_key(device_id, "resolve-ref")


def test_resolve_local_ref_cross_device_miss(client: TestClient, *, identity) -> None:
    device_id = _owner_device_id(identity)
    _create_manual(client, identity.app_headers, client_ref="resolve-ref")
    with SessionLocal() as db:
        # Same client_ref, a DIFFERENT device → different composite key → miss.
        assert resolve_expense(db, "owner", "local:resolve-ref", device_id=device_id + 999) is None


def test_resolve_local_ref_cross_tenant_miss(client: TestClient, *, identity) -> None:
    device_id = _owner_device_id(identity)
    _create_manual(client, identity.app_headers, client_ref="resolve-ref")
    with SessionLocal() as db:
        assert resolve_expense(db, "tester_1", "local:resolve-ref", device_id=device_id) is None


def test_resolve_local_ref_without_device_is_none(client: TestClient, *, identity) -> None:
    _create_manual(client, identity.app_headers, client_ref="resolve-ref")
    with SessionLocal() as db:
        # The route layer (slice 3) supplies the device; without it a local ref can't resolve.
        assert resolve_expense(db, "owner", "local:resolve-ref") is None


def test_audit_flags_scattered_but_not_resolver_or_projection() -> None:
    audit = _load_audit()
    scattered = (
        "current = db.scalar(\n"
        "    ledger_scoped_select(Expense, tenant_id).where(Expense.id == expense_id)\n"
        ")"
    )
    resolver = "db.scalar(ledger_scoped_select(Expense, tenant_id).where(Expense.id == int(ref)))"
    projection = (
        "ledger_scoped_select(Expense, tenant_id)\n"
        "    .with_only_columns(Expense.id)\n"
        "    .where(Expense.id == expense_id)"
    )
    assert audit.find_violations(scattered), "must flag a scattered full-row resolve"
    assert not audit.find_violations(resolver), "resolve_expense's own int(ref) lookup is not a violation"
    assert not audit.find_violations(projection), "a projection (with_only_columns) is not a full-row resolve"
