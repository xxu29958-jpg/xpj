"""Accepted split replacements replay their first result without advancing OCC.

The first receipt and rows share a transaction. A peer's later changes stay
visible through GET and cannot become the basis of the next offline command.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from api_contract_helpers import patch_expense, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, LedgerMember
from app.schemas import ExpenseSplitReplaceRequest
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    fingerprint_request,
)
from app.services.time_service import now_utc


def _owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return member.id


def _pending_expense(client: TestClient, *, identity, amount_cents: int = 1500) -> int:
    expense_id = upload_png(client, identity=identity)
    resp = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": amount_cents,
            "merchant": "Idem Splits",
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    return expense_id


def _row_version(client: TestClient, expense_id: int, *, identity) -> int:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["row_version"])


def test_replace_splits_requires_idempotency_key(client: TestClient, *, identity) -> None:
    expense_id = _pending_expense(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    member_id = _owner_member_id()
    resp = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=identity.app_headers,
        json={"expected_row_version": v0, "splits": [{"member_id": member_id, "amount_cents": 1500}]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


def test_replace_splits_replay_preserves_original_acceptance_after_peer_change(
    client: TestClient, *, identity
) -> None:
    """An accepted replay keeps its first result after a later peer edit."""
    expense_id = _pending_expense(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    member_id = _owner_member_id()
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {
        "expected_row_version": v0,
        "splits": [{"member_id": member_id, "amount_cents": 1500, "note": "first"}],
    }

    first = client.put(f"/api/expenses/{expense_id}/splits", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert [s["amount_cents"] for s in first.json()["splits"]] == [1500]
    v1 = first.json()["row_version"]
    assert v1 != v0

    peer = client.put(f"/api/expenses/{expense_id}/splits",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": v1, "splits": [{"member_id": member_id, "amount_cents": 700, "note": "他端后来填写"}]})
    assert peer.status_code == 200, peer.text

    replay = client.put(f"/api/expenses/{expense_id}/splits", headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    following = client.put(f"/api/expenses/{expense_id}/splits",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={**body, "expected_row_version": replay.json()["row_version"]})
    assert following.status_code == 409, following.text
    assert following.json()["error"] == "state_conflict"
    assert client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers).json() == peer.json()


def test_replace_splits_stale_token_with_different_key_still_409s(
    client: TestClient, *, identity
) -> None:
    """Negative control: a DIFFERENT key with the same now-stale token is a
    genuine concurrent writer → OCC 409 stays intact."""
    expense_id = _pending_expense(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    member_id = _owner_member_id()
    body = {"expected_row_version": v0, "splits": [{"member_id": member_id, "amount_cents": 1500}]}

    first = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_replace_splits_in_progress_returns_409(client: TestClient, *, identity) -> None:
    """A fresh in_progress placeholder (same key + matching fingerprint) blocks a
    concurrent same-key request → 409 idempotency_key_in_progress. The fingerprint
    body is the splits list (``expected_row_version`` excluded) — exactly what the
    route computes."""
    expense_id = _pending_expense(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    member_id = _owner_member_id()
    splits = [{"member_id": member_id, "amount_cents": 1500}]
    key = str(uuid4())
    payload = ExpenseSplitReplaceRequest(expected_row_version=v0, splits=splits)
    fingerprint = fingerprint_request(
        operation="replace_splits",
        target_id=str(expense_id),
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="replace_splits",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": v0, "splits": splits},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_replace_splits_same_key_different_body_is_reused_422(
    client: TestClient, *, identity
) -> None:
    """§4.7: same key, different request (a different split amount) → 422
    idempotency_key_reused before any mutation."""
    expense_id = _pending_expense(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    member_id = _owner_member_id()
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=headers,
        json={"expected_row_version": v0, "splits": [{"member_id": member_id, "amount_cents": 1500}]},
    )
    assert first.status_code == 200, first.text

    reused = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=headers,
        json={"expected_row_version": v0, "splits": [{"member_id": member_id, "amount_cents": 9999}]},
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"
