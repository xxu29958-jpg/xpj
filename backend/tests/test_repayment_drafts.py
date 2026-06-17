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

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember
from app.services import debt_service
from app.services.time_service import now_utc

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


# --- list: §杠杆③ slice 3b server-suggested target Debt --------------------------


def _create_external_debt(
    client: TestClient,
    identity,
    *,
    counterparty_label: str,
    principal_amount_cents: int = 50000,
) -> dict:
    response = client.post(
        "/api/debts",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": counterparty_label,
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _listed(client: TestClient, identity, *, public_id: str, status: str = "pending") -> dict:
    listing = client.get(
        f"/api/repayment-drafts?status={status}", headers=identity.app_headers
    ).json()
    match = next((d for d in listing["items"] if d["public_id"] == public_id), None)
    assert match is not None, listing
    return match


def test_list_pending_draft_carries_server_suggestion(client: TestClient, *, identity) -> None:
    # An open external/manual Debt labeled the same as the captured platform → the inbox list
    # pre-selects it via suggested_debt_public_id (ephemeral — computed in the list path).
    debt = _create_external_debt(client, identity, counterparty_label="花呗")
    draft = _create_draft(client, identity, merchant_label="花呗", amount_cents=20000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] == debt["public_id"]


def test_list_suggestion_absent_when_ambiguous(client: TestClient, *, identity) -> None:
    # Two open Debt both labeled 花呗 both feasible → the match is ambiguous → no suggestion
    # (the user picks). Exercises the real candidate query returning >1 plus the matcher tie.
    _create_external_debt(client, identity, counterparty_label="花呗")
    _create_external_debt(client, identity, counterparty_label="花呗")
    draft = _create_draft(client, identity, merchant_label="花呗", amount_cents=10000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] is None


def test_list_suggestion_only_for_pending_not_resolved(client: TestClient, *, identity) -> None:
    # The suggestion is for the review action; once a draft is resolved it carries none, even
    # though the candidate Debt still exists.
    _create_external_debt(client, identity, counterparty_label="花呗")
    draft = _create_draft(client, identity, merchant_label="花呗", amount_cents=10000)
    # Pending → suggestion present.
    assert _listed(client, identity, public_id=draft["public_id"])["suggested_debt_public_id"]
    dismiss = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert dismiss.status_code == 201, dismiss.json()
    resolved = _listed(client, identity, public_id=draft["public_id"], status="dismissed")
    assert resolved["suggested_debt_public_id"] is None


def test_service_unfiltered_list_suggests_only_pending_drafts(client: TestClient, *, identity) -> None:
    # The route always filters by ONE status (default pending), so a pending-only list never
    # co-lists a resolved draft — the per-draft `status == "pending"` guard only bites on a
    # status=None mixed list (e.g. a future all-statuses view), reachable at the service level.
    # Pin it there: a pending AND a dismissed draft that BOTH match the same Debt → only the
    # pending one carries the suggestion. (Mutation: drop the per-draft pending guard → the
    # dismissed draft, co-listed while has_pending=True keeps candidates non-empty, also gets one.)
    debt = _create_external_debt(client, identity, counterparty_label="花呗")
    pending = _create_draft(
        client, identity, merchant_label="花呗", amount_cents=20000, notification_key="mix-pending"
    )
    resolved = _create_draft(
        client, identity, merchant_label="花呗", amount_cents=20000, notification_key="mix-dismissed"
    )
    dismiss = client.post(
        f"/api/repayment-drafts/{resolved['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert dismiss.status_code == 201, dismiss.json()

    with SessionLocal() as db:
        listing = debt_service.list_repayment_drafts(db, tenant_id="owner", status=None)
    by_id = {item.public_id: item for item in listing.items}
    assert by_id[pending["public_id"]].suggested_debt_public_id == debt["public_id"]
    assert by_id[resolved["public_id"]].suggested_debt_public_id is None


def _seed_debt_orm(
    *,
    counterparty_type: str,
    source_type: str,
    status: str,
    label: str = "花呗",
    principal_amount_cents: int = 50000,
) -> str:
    """ORM-seed a tenant 'owner' Debt of an arbitrary shape (bypasses the create-path guards so the
    candidate query's WHERE-clause exclusions can be exercised directly)."""
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        assert owner is not None
        now = now_utc()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner.id,
            created_by_account_id=owner.id,
            direction="i_owe",
            counterparty_type=counterparty_type,
            counterparty_label=label,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status=status,
            source_type=source_type,
            created_at=now,
            updated_at=now,
        )
        db.add(debt)
        db.commit()
        return debt.public_id


def test_list_suggestion_excludes_non_repayable_debt_shapes(client: TestClient, *, identity) -> None:
    # The candidate query keeps the suggestion to a repayable target (open + external + manual),
    # mirroring guard_direct_fact_writable / the Android isRepayableDebt. Seed each excluded shape
    # as the ONLY 花呗 Debt — a dropped WHERE clause would make exactly one a candidate and surface
    # a non-repayable suggestion. With all filters intact the 花呗 draft has no confident match.
    _seed_debt_orm(counterparty_type="external", source_type="manual", status="voided")  # bites status!='voided'
    _seed_debt_orm(counterparty_type="member", source_type="manual", status="open")  # bites counterparty='external'
    _seed_debt_orm(counterparty_type="external", source_type="bill_split", status="open")  # bites source='manual'
    draft = _create_draft(client, identity, merchant_label="花呗", amount_cents=20000)
    listed = _listed(client, identity, public_id=draft["public_id"])
    assert listed["suggested_debt_public_id"] is None


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
