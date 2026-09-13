"""Issue #65 slice 1 — device-scoped idempotent manual create (``client_ref``).

``POST /api/expenses/manual`` with a ``client_ref`` dedups on the server-built
``{device_id}:{client_ref}`` composite (stored in ``expenses.draft_idempotency_key``):

* same device + same ref + same body → one row and the original response (HIT);
* same device + same ref + materially different body → ``idempotency_key_reused`` (422);
* the shared receipt claim serializes concurrent original submissions;
* absent, null or blank ``client_ref`` → refusal before a fact is created;
* the device prefix namespaces refs, so two devices may reuse the same ref independently.

The fingerprint is taken from the REQUEST, so the server auto-classifying ``category`` (or
defaulting ``expense_time``) on the stored row never makes a faithful replay look different.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.services.expense_service._create as create_module
from app.database import SessionLocal
from app.models import AuthToken, Device, Expense
from app.services.identity_service import hash_secret, new_session_token
from tests._runtime_protocol import current_protocol_headers


def _manual_payload(**overrides) -> dict:
    body = {
        "home_currency_code": "CNY",
        "amount_cents": 1000,
        "merchant": "测试商家",
        "category": "餐饮",
        "expense_time": "2026-05-02T00:00:00Z",
        "client_ref": "ref-default",
    }
    body.update(overrides)
    return body


def _post_manual(client: TestClient, headers: dict[str, str], **overrides):
    return client.post("/api/expenses/manual", headers=headers, json=_manual_payload(**overrides))


def _count_manual_rows(tenant_id: str = "owner") -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == tenant_id, Expense.source == "手动记账")
        )


def _stored_amount_for_ref(client_ref: str, tenant_id: str = "owner") -> int:
    with SessionLocal() as db:
        row = db.scalar(
            select(Expense).where(
                Expense.tenant_id == tenant_id,
                Expense.draft_idempotency_key.like(f"%:{client_ref}"),
            )
        )
        assert row is not None
        return row.amount_cents


def _add_second_owner_device(identity) -> str:
    """Issue a second app token bound to a NEW device on the SAME owner ledger."""
    with SessionLocal() as db:
        owner_tok = (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(identity.app_token))
            .one()
        )
        device = Device(
            account_id=owner_tok.account_id,
            device_name="pytest-android-2",
            platform="android",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=owner_tok.account_id,
                device_id=device.id,
                ledger_id=owner_tok.ledger_id,
                scope="app",
            )
        )
        db.commit()
    return token


def test_manual_create_without_auth_is_401(client: TestClient, *, identity) -> None:
    response = client.post("/api/expenses/manual", json=_manual_payload())
    assert response.status_code == 401


def test_same_client_ref_same_body_is_idempotent(client: TestClient, *, identity) -> None:
    first = _post_manual(client, identity.app_headers, client_ref="ref-idem")
    assert first.status_code == 200, first.text
    second = _post_manual(client, identity.app_headers, client_ref="ref-idem")
    assert second.status_code == 200, second.text

    assert second.json()["id"] == first.json()["id"]
    assert _count_manual_rows() == 1


def test_client_ref_replay_with_auto_classified_category_is_idempotent(
    client: TestClient, *, identity
) -> None:
    # No category sent → the server auto-classifies the stored row. A faithful replay
    # (also omitting category) must still HIT, not 422 on the now-classified row.
    body = {
        "home_currency_code": "CNY",
        "amount_cents": 4200,
        "merchant": "全家便利店",
        "expense_time": "2026-05-03T00:00:00Z",
        "client_ref": "ref-autocat",
    }
    first = client.post("/api/expenses/manual", headers=identity.app_headers, json=body)
    assert first.status_code == 200, first.text
    # Precondition: the server actually auto-classified (no category sent → seeded
    # "便利店"→餐饮 rule fires). Asserting it means that if default-rule seeding ever
    # breaks this test fails LOUDLY, instead of silently decaying into a plain
    # same-body idempotency check that no longer exercises the auto-classify scenario.
    assert first.json()["category"] == "餐饮"
    second = client.post("/api/expenses/manual", headers=identity.app_headers, json=body)
    assert second.status_code == 200, second.text

    assert second.json()["id"] == first.json()["id"]
    assert _count_manual_rows() == 1


def test_same_client_ref_different_amount_is_rejected(client: TestClient, *, identity) -> None:
    first = _post_manual(client, identity.app_headers, client_ref="ref-amt", amount_cents=1000)
    assert first.status_code == 200, first.text
    conflict = _post_manual(client, identity.app_headers, client_ref="ref-amt", amount_cents=2000)
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["error"] == "idempotency_key_reused"
    assert _count_manual_rows() == 1
    # The rejected replay must NOT have mutated the original row.
    assert _stored_amount_for_ref("ref-amt") == 1000


def test_same_client_ref_different_merchant_is_rejected(client: TestClient, *, identity) -> None:
    first = _post_manual(client, identity.app_headers, client_ref="ref-mer", merchant="A 店")
    assert first.status_code == 200, first.text
    conflict = _post_manual(client, identity.app_headers, client_ref="ref-mer", merchant="B 店")
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["error"] == "idempotency_key_reused"
    assert _count_manual_rows() == 1


def test_same_client_ref_different_note_is_rejected(client: TestClient, *, identity) -> None:
    first = _post_manual(client, identity.app_headers, client_ref="ref-note", note="原始备注")
    assert first.status_code == 200, first.text
    conflict = _post_manual(client, identity.app_headers, client_ref="ref-note", note="改过的备注")
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["error"] == "idempotency_key_reused"
    assert _count_manual_rows() == 1


@pytest.mark.parametrize("fields", [{}, {"client_ref": None}, {"client_ref": ""}, {"client_ref": "   "}])
def test_missing_original_reference_is_refused_without_creating(client: TestClient, *, identity, fields) -> None:
    body = _manual_payload()
    body.pop("client_ref")
    body.update(fields)
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_request"
    assert _count_manual_rows() == 0


def test_same_client_ref_different_device_creates_distinct_rows(
    client: TestClient, *, identity
) -> None:
    second_token = _add_second_owner_device(identity)
    second_headers = current_protocol_headers({"Authorization": f"Bearer {second_token}"})

    first = _post_manual(client, identity.app_headers, client_ref="shared-ref")
    second = _post_manual(client, second_headers, client_ref="shared-ref")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    # Same client_ref, different device → distinct server-built keys → two rows.
    assert second.json()["id"] != first.json()["id"]
    assert _count_manual_rows() == 2


def test_receipt_replay_does_not_reenter_expense_insert_or_current_lookup(client, identity, monkeypatch):
    created = _post_manual(client, identity.app_headers, client_ref="ref-original")
    assert created.status_code == 200, created.text
    def reject_current_lookup(*_args, **_kwargs):
        pytest.fail("The original receipt must bypass latest expense lookup")
    monkeypatch.setattr(create_module, "_find_manual_expense_by_key", reject_current_lookup)
    monkeypatch.setattr(create_module, "_insert_manual_expense", reject_current_lookup)
    replay = _post_manual(client, identity.app_headers, client_ref="ref-original")
    assert replay.status_code == 200, replay.text
    assert replay.json() == created.json()
    assert _count_manual_rows() == 1
