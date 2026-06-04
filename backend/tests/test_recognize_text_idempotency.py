"""ADR-0042 Slice E-2: request-idempotency for the recognize-text route.

Same uniform contract as retry-OCR (Slice D-1): ``POST /recognize-text`` claims
its ``Idempotency-Key`` (via the shared ``claim_idempotent_request``) BEFORE the
atomic OCC claim. A committed-but-unseen replay (same key + now-stale token)
re-serialises the canonical expense via ``get_expense`` + ``expense_to_response``
instead of the false-409 the OCC claim would raise on the bumped row_version.

recognize-text only operates on ``status == "pending"`` rows, so the fixture
uploads a PNG (pending) rather than creating a manual (confirmed) expense.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from api_contract_helpers import upload_png
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.schemas import ExpenseRecognizeTextRequest
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    fingerprint_request,
)
from app.services.time_service import now_utc

_RAW_TEXT = "中国建设银行\n交易金额：18.51"


def _row_version(client: TestClient, expense_id: int, *, identity) -> int:
    resp = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["row_version"])


def test_recognize_text_requires_idempotency_key(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    resp = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"expected_row_version": v0, "raw_text": _RAW_TEXT},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


def test_recognize_text_replay_same_key_returns_canonical_not_409(
    client: TestClient, *, identity
) -> None:
    """Committed-but-unseen: the SAME key + SAME now-stale token re-serialises the
    (already-recognised) expense via get_expense rather than the false-409 the OCC
    claim would raise on the bumped row_version."""
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"expected_row_version": v0, "raw_text": _RAW_TEXT}

    first = client.post(f"/api/expenses/{expense_id}/recognize-text", headers=headers, json=body)
    assert first.status_code == 200, first.text
    v1 = first.json()["row_version"]
    assert v1 != v0
    recognized_merchant = first.json()["merchant"]

    replay = client.post(f"/api/expenses/{expense_id}/recognize-text", headers=headers, json=body)
    assert replay.status_code == 200, replay.text  # HIT, not 409
    assert replay.json()["row_version"] == v1  # canonical, not re-applied
    assert replay.json()["merchant"] == recognized_merchant


def test_recognize_text_stale_token_with_different_key_still_409s(
    client: TestClient, *, identity
) -> None:
    """Negative control: a DIFFERENT key with the same now-stale token is a
    genuine concurrent writer → OCC 409 stays intact."""
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    body = {"expected_row_version": v0, "raw_text": _RAW_TEXT}

    first = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_recognize_text_in_progress_returns_409(client: TestClient, *, identity) -> None:
    """A fresh in_progress placeholder (same key + matching fingerprint) blocks a
    concurrent same-key request → 409 idempotency_key_in_progress. The fingerprint
    body is the raw_text (``expected_row_version`` excluded) — exactly what the
    route computes."""
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    payload = ExpenseRecognizeTextRequest(expected_row_version=v0, raw_text=_RAW_TEXT)
    fingerprint = fingerprint_request(
        operation="recognize_text",
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
                operation="recognize_text",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": v0, "raw_text": _RAW_TEXT},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_recognize_text_same_key_different_body_is_reused_422(
    client: TestClient, *, identity
) -> None:
    """§4.7: same key, different request (different raw_text) → 422
    idempotency_key_reused before any mutation."""
    expense_id = upload_png(client, identity=identity)
    v0 = _row_version(client, expense_id, identity=identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=headers,
        json={"expected_row_version": v0, "raw_text": _RAW_TEXT},
    )
    assert first.status_code == 200, first.text

    reused = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=headers,
        json={"expected_row_version": v0, "raw_text": "完全不同的文字"},
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"
