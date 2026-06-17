"""ADR-0049 §杠杆③ NLS repayment-capture — confirm into a Debt (slice 3a).

Confirming a pending draft records ONE ``Repayment`` against a user-chosen open
external/manual Debt via the slice-2 ``record_repayment`` path (same §2.1 lock + overpay
+ OCC guards), then latches the draft confirmed. Pins: records-once + reduces remaining;
the external/manual guard (member Debt → 409); overpay (422); stale OCC (409); missing
Debt/draft (404); Idempotency-Key required (422); idempotent replay (once);
already-resolved (409); viewer (403); no-auth (401); dismiss-of-a-confirmed-draft (409);
and two concurrent confirms serialize on the draft row so the repayment lands exactly once.

Capture / list / plain dismiss live in ``test_repayment_drafts.py`` (file split to stay
under the 500-line budget). API assertions read the rendered response / a GET re-read,
never a DB peek; the ``test_two_sessions_*`` tests seed via ORM + drive the service to
model true FOR UPDATE contention the shared-savepoint connection cannot.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal, engine
from app.errors import AppError
from app.models import Account, Debt, LedgerMember, Repayment, RepaymentDraft
from app.services import debt_service
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _create_debt(client: TestClient, identity, *, principal_amount_cents: int = 50000) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "花呗",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_draft(client: TestClient, identity, *, amount_cents: int, notification_key: str | None = None) -> dict:
    body: dict[str, object] = {
        "source": "alipay",
        "amount_cents": amount_cents,
        "merchant_label": "花呗",
    }
    if notification_key is not None:
        body["notification_key"] = notification_key
    response = client.post("/api/repayment-drafts", headers=identity.app_headers, json=body)
    assert response.status_code == 201, response.json()
    return response.json()


def _confirm(client: TestClient, identity, draft_id: str, debt: dict, *, headers: dict | None = None):
    return client.post(
        f"/api/repayment-drafts/{draft_id}/confirm",
        headers=headers if headers is not None else _idem(identity.app_headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )


# --- confirm --------------------------------------------------------------------


def test_confirm_records_repayment_and_reduces_remaining(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    draft = _create_draft(client, identity, amount_cents=20000)
    response = _confirm(client, identity, draft["public_id"], debt)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["committed_debt_public_id"] == debt["public_id"]
    assert body["committed_repayment_public_id"]
    assert body["resolved_at"]
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["remaining_amount_cents"] == 30000
    assert detail["paid_amount_cents"] == 20000


def test_confirm_clearing_debt_latches_cleared(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=20000)
    draft = _create_draft(client, identity, amount_cents=20000)
    response = _confirm(client, identity, draft["public_id"], debt)
    assert response.status_code == 201, response.json()
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["status"] == "cleared"
    assert detail["remaining_amount_cents"] == 0


def test_confirm_overpay_is_rejected_and_draft_stays_pending(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=10001)
    response = _confirm(client, identity, draft["public_id"], debt)
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_overpay_rejected"
    # The draft latch rolled back with the rejected repayment — still reviewable.
    listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert any(
        d["public_id"] == draft["public_id"] and d["status"] == "pending"
        for d in listing["items"]
    )


def test_confirm_against_member_debt_is_conflict(client: TestClient, *, identity) -> None:
    # A member Debt is not directly writable (it goes through the proposal flow), so a
    # captured repayment cannot be confirmed against it — record_repayment guards it.
    member_debt = _seed_manual_member_debt(principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=1000)
    response = _confirm(client, identity, draft["public_id"], member_debt)
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_confirm_stale_debt_version_is_conflict(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    draft_a = _create_draft(client, identity, amount_cents=5000, notification_key="stale-a")
    first = _confirm(client, identity, draft_a["public_id"], debt)
    assert first.status_code == 201, first.json()
    # A second draft confirmed with the now-stale original debt version → 409.
    draft_b = _create_draft(client, identity, amount_cents=5000, notification_key="stale-b")
    stale = _confirm(client, identity, draft_b["public_id"], debt)
    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "state_conflict"


def test_confirm_missing_debt_is_404(client: TestClient, *, identity) -> None:
    draft = _create_draft(client, identity, amount_cents=1000)
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"target_debt_public_id": "does-not-exist", "expected_row_version": 1},
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "debt_not_found"


def test_confirm_missing_draft_is_404(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        "/api/repayment-drafts/does-not-exist/confirm",
        headers=_idem(identity.app_headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "repayment_draft_not_found"


def test_confirm_idempotent_replay_records_once(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    draft = _create_draft(client, identity, amount_cents=15000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    first = _confirm(client, identity, draft["public_id"], debt, headers=headers)
    assert first.status_code == 201, first.json()
    repayment_id = first.json()["committed_repayment_public_id"]
    # Same key → canonical re-serialise, no second repayment recorded.
    replay = _confirm(client, identity, draft["public_id"], debt, headers=headers)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["status"] == "confirmed"
    assert replay.json()["committed_repayment_public_id"] == repayment_id
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["remaining_amount_cents"] == 35000  # 50000 - 15000, applied once


def test_confirm_missing_idempotency_key_is_422(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=1000)
    response = _confirm(client, identity, draft["public_id"], debt, headers=identity.app_headers)
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_confirm_already_confirmed_with_new_key_is_conflict(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    draft = _create_draft(client, identity, amount_cents=5000)
    first = _confirm(client, identity, draft["public_id"], debt)
    assert first.status_code == 201, first.json()
    refreshed = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    # A DIFFERENT key confirming the already-confirmed draft cannot record again.
    again = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": refreshed["row_version"]},
    )
    assert again.status_code == 409, again.json()
    assert again.json()["error"] == "state_conflict"
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["paid_amount_cents"] == 5000  # exactly one repayment landed


def test_confirm_viewer_is_403(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=1000)
    _set_owner_ledger_role("viewer")
    response = _confirm(client, identity, draft["public_id"], debt)
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_confirm_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=1000)
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 401


def test_dismiss_confirmed_draft_is_conflict(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    draft = _create_draft(client, identity, amount_cents=1000)
    confirm = _confirm(client, identity, draft["public_id"], debt)
    assert confirm.status_code == 201, confirm.json()
    response = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=identity.app_headers, json={}
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


# --- ORM seeds for the member-debt guard + concurrency tests --------------------


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_manual_member_debt(*, principal_amount_cents: int = 10000) -> dict:
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        assert owner is not None
        counterparty = Account(display_name="rd-member-counterparty")
        db.add(counterparty)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=counterparty.id, role="member"))
        now = now_utc()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner.id,
            created_by_account_id=owner.id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=counterparty.id,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status="open",
            source_type="manual",
            created_at=now,
            updated_at=now,
        )
        db.add(debt)
        db.commit()
        return {"public_id": debt.public_id, "row_version": debt.row_version}


def _seed_committed_external_debt(*, principal_amount_cents: int) -> tuple[str, int]:
    actor = _owner_account_id()
    with SessionLocal() as db:
        from app.schemas import DebtCreateRequest

        debt = debt_service.create_debt(
            db,
            tenant_id="owner",
            created_by_account_id=actor,
            owner_account_id=actor,
            payload=DebtCreateRequest(
                direction="i_owe",
                counterparty_type="external",
                counterparty_label="花呗",
                principal_amount_cents=principal_amount_cents,
            ),
            commit=True,
        )
        return debt.public_id, debt.row_version


def _seed_committed_draft(*, amount_cents: int) -> str:
    actor = _owner_account_id()
    with SessionLocal() as db:
        from app.schemas import RepaymentDraftCreateRequest

        draft = debt_service.create_repayment_draft(
            db,
            payload=RepaymentDraftCreateRequest(
                source="alipay",
                amount_cents=amount_cents,
                merchant_label="花呗",
                notification_key=str(uuid4()),
            ),
            tenant_id="owner",
            actor_account_id=actor,
        )
        return draft.public_id


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="row-lock contention is only observable on the PostgreSQL lane; "
    "FOR UPDATE is a no-op on SQLite",
)
def test_two_sessions_confirm_serializes_on_draft_row(*, identity) -> None:
    """Session A holds FOR UPDATE on the draft row; session B's confirm blocks on it.
    A short ``lock_timeout`` turns the contention into a deterministic OperationalError
    instead of a hang — proving the draft row is the serialization point, so two confirms
    can never each record a repayment for the same captured draft."""
    debt_public_id, debt_version = _seed_committed_external_debt(principal_amount_cents=50000)
    draft_public_id = _seed_committed_draft(amount_cents=10000)
    actor = _owner_account_id()

    holder = SessionLocal()
    try:
        holder.scalar(
            select(RepaymentDraft)
            .where(RepaymentDraft.public_id == draft_public_id)
            .with_for_update()
        )
        with SessionLocal() as blocked, pytest.raises(OperationalError):
            blocked.execute(text("SET LOCAL lock_timeout = '500ms'"))
            debt_service.confirm_repayment_draft(
                blocked,
                tenant_id="owner",
                actor_account_id=actor,
                public_id=draft_public_id,
                target_debt_public_id=debt_public_id,
                expected_row_version=debt_version,
                idempotency_key=str(uuid4()),
                commit=True,
            )
    finally:
        holder.rollback()
        holder.close()

    # No repayment landed (B never got past the lock; A only held it).
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert repayments == []


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="cross-session committed-state visibility needs the real PostgreSQL lane",
)
def test_two_sessions_confirm_serialize_then_second_rechecks(*, identity) -> None:
    """Serialize-then-recheck: A confirms a draft (records one repayment), B confirming
    the SAME draft sees it non-pending → 409, so the captured repayment is recorded exactly
    once across two confirms."""
    debt_public_id, debt_version = _seed_committed_external_debt(principal_amount_cents=50000)
    draft_public_id = _seed_committed_draft(amount_cents=10000)
    actor = _owner_account_id()

    with SessionLocal() as session_a:
        debt_service.confirm_repayment_draft(
            session_a,
            tenant_id="owner",
            actor_account_id=actor,
            public_id=draft_public_id,
            target_debt_public_id=debt_public_id,
            expected_row_version=debt_version,
            idempotency_key=str(uuid4()),
            commit=True,
        )

    with SessionLocal() as session_b, pytest.raises(AppError) as exc_info:
        debt_service.confirm_repayment_draft(
            session_b,
            tenant_id="owner",
            actor_account_id=actor,
            public_id=draft_public_id,
            target_debt_public_id=debt_public_id,
            expected_row_version=debt_version + 1,
            idempotency_key=str(uuid4()),
            commit=True,
        )
    assert exc_info.value.error == "state_conflict"

    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 1
        assert repayments[0].amount_cents == 10000
