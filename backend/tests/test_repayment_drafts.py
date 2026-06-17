"""ADR-0049 §杠杆③ NLS repayment-capture inbox — capture / list / dismiss (slice 3a).

The Android NLS captures a *repayment* notification as a PENDING draft (never an
auto-recorded fact, §8). This file pins capture + the review inbox + dismiss; the
confirm-into-a-Debt path lives in ``test_repayment_drafts_confirm.py`` (split to keep
each file under the 500-line layering budget).

- capture: content+identity dedup (re-posted notification → one draft; distinct posts →
  distinct drafts), invalid channel → 422, viewer → 403, no-auth → 401.
- list: the pending inbox, status-filtered.
- dismiss: latches dismissed (idempotent if already dismissed), no-auth → 401.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _create_draft(
    client: TestClient,
    identity,
    *,
    source: str = "alipay",
    amount_cents: int = 20000,
    merchant_label: str | None = "花呗",
    notification_key: str | None = None,
) -> dict:
    body: dict[str, object] = {
        "source": source,
        "amount_cents": amount_cents,
    }
    if merchant_label is not None:
        body["merchant_label"] = merchant_label
    if notification_key is not None:
        body["notification_key"] = notification_key
    response = client.post("/api/repayment-drafts", headers=identity.app_headers, json=body)
    assert response.status_code == 201, response.json()
    return response.json()


# --- capture --------------------------------------------------------------------


def test_capture_creates_pending_draft(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, amount_cents=30000, merchant_label="借呗")
    assert draft["status"] == "pending"
    assert draft["source"] == "alipay"
    assert draft["amount_cents"] == 30000
    assert draft["home_currency_code"] == "CNY"
    assert draft["merchant_label"] == "借呗"
    assert draft["committed_debt_public_id"] is None
    assert draft["committed_repayment_public_id"] is None
    assert draft["public_id"]
    assert draft["captured_at"]  # defaulted to now when omitted


def test_capture_dedupes_same_notification_identity(client: TestClient, *, identity) -> None:
    first = _create_draft(client, identity, amount_cents=12345, notification_key="ident-abc")
    second = _create_draft(client, identity, amount_cents=12345, notification_key="ident-abc")
    # Same per-post identity + content → the existing draft, not a twin.
    assert second["public_id"] == first["public_id"]
    listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert sum(1 for d in listing["items"] if d["public_id"] == first["public_id"]) == 1


def test_capture_distinct_identities_same_content_create_two(
    client: TestClient, *, identity
) -> None:
    first = _create_draft(client, identity, amount_cents=9900, notification_key="ident-1")
    second = _create_draft(client, identity, amount_cents=9900, notification_key="ident-2")
    # Two genuinely distinct posts (same咖啡 twice) → two reviewable drafts (codex PR#20).
    assert second["public_id"] != first["public_id"]


def test_capture_invalid_source_is_422(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "venmo", "amount_cents": 1000},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "notification_source_invalid"


def test_capture_home_currency_is_server_set(client: TestClient, *, identity) -> None:
    # home_currency_code is NOT a client input — the server sets it from the configured
    # home currency, so a capture that omits it still records the home currency, and the
    # field cannot be used to smuggle a foreign currency past confirm.
    draft = _create_draft(client, identity, amount_cents=20000)
    assert draft["home_currency_code"] == "CNY"


def test_capture_viewer_is_403(client: TestClient, *, identity) -> None:
    _set_owner_ledger_role("viewer")
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": 1000},
    )
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_capture_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/repayment-drafts",
        json={"source": "alipay", "amount_cents": 1000},
    )
    assert response.status_code == 401


# --- list -----------------------------------------------------------------------


def test_list_returns_pending_and_filters_by_status(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, notification_key="list-1")
    pending = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert any(d["public_id"] == draft["public_id"] for d in pending["items"])
    # A status that no draft holds yet returns an empty inbox.
    confirmed = client.get(
        "/api/repayment-drafts?status=confirmed", headers=identity.app_headers
    ).json()
    assert all(d["public_id"] != draft["public_id"] for d in confirmed["items"])


# --- dismiss --------------------------------------------------------------------


def test_dismiss_latches_dismissed(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, amount_cents=4200)
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "dismissed"
    assert response.json()["resolved_at"]


def test_dismiss_is_idempotent_when_already_dismissed(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, amount_cents=4200)
    first = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert first.status_code == 201, first.json()
    again = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert again.status_code == 201, again.json()
    assert again.json()["status"] == "dismissed"


def test_dismiss_viewer_is_403(client: TestClient, *, identity) -> None:
    # dismiss is a writers-only destructive op; its get_current_writer_context dep is
    # per-handler, so it needs its own viewer-403 pin (capture/confirm cover their handlers).
    draft = _create_draft(client, identity, amount_cents=1000)
    _set_owner_ledger_role("viewer")
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_dismiss_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, amount_cents=1000)
    response = client.post(f"/api/repayment-drafts/{draft['public_id']}/dismiss", json={})
    assert response.status_code == 401
