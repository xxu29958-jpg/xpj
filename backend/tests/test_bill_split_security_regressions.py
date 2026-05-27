"""Security regressions for ADR-0029 bill split boundaries."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import (
    AuthToken,
    BillSplitInvitation,
    Device,
    Expense,
    Ledger,
    LedgerMember,
)
from app.services import bill_split_service as bsplit
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc
from tests.test_bill_split import (
    _make_expense_for_owner,
    _owner_account_id,
    _seed_receiver,
)


def _bearer_for_account_ledger(account_id: int, ledger_id: str) -> dict[str, str]:
    with SessionLocal() as db:
        device = Device(
            account_id=account_id,
            device_name="pytest-bill-split",
            platform="android",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
    return {"Authorization": f"Bearer {token}"}


def _expense_snapshot(expense_id: int, tenant_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.id == expense_id)
            .where(Expense.tenant_id == tenant_id)
        )
        assert expense is not None
        return {
            "amount_cents": expense.amount_cents,
            "merchant": expense.merchant,
            "category": expense.category,
            "note": expense.note,
            "image_path": expense.image_path,
            "raw_text": expense.raw_text,
            "source": expense.source,
        }


def _add_viewer_ledger(ledger_id: str, account_id: int, owner_account_id: int) -> None:
    with SessionLocal() as db:
        db.add(Ledger(
            ledger_id=ledger_id,
            name="Viewer current ledger",
            owner_account_id=owner_account_id,
        ))
        db.flush()
        db.add(LedgerMember(
            ledger_id=ledger_id,
            account_id=account_id,
            role="viewer",
        ))
        db.commit()


def test_accept_route_allows_current_viewer_when_target_ledger_is_writer(
    client: TestClient, *, identity
) -> None:
    """Route auth must not confuse the current ledger with the accept target."""
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-route-accept",
        ledger_id="receiver_route_accept_target",
    )
    _add_viewer_ledger(
        "receiver_route_accept_viewer",
        account_id=receiver_account_id,
        owner_account_id=_owner_account_id(),
    )

    create_resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 2500},
    )
    assert create_resp.status_code == 200, create_resp.json()
    public_id = create_resp.json()["public_id"]

    accept_resp = client.post(
        f"/api/bill-splits/{public_id}/accept",
        headers=_bearer_for_account_ledger(
            receiver_account_id,
            "receiver_route_accept_viewer",
        ),
        json={"target_ledger_id": "receiver_route_accept_target"},
    )

    assert accept_resp.status_code == 200, accept_resp.json()
    assert accept_resp.json()["status"] == "accepted"


def test_reject_route_allows_current_viewer_ledger(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-route-reject",
        ledger_id="receiver_route_reject_target",
    )
    _add_viewer_ledger(
        "receiver_route_reject_viewer",
        account_id=receiver_account_id,
        owner_account_id=_owner_account_id(),
    )

    create_resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 2500},
    )
    assert create_resp.status_code == 200, create_resp.json()
    public_id = create_resp.json()["public_id"]

    reject_resp = client.post(
        f"/api/bill-splits/{public_id}/reject",
        headers=_bearer_for_account_ledger(
            receiver_account_id,
            "receiver_route_reject_viewer",
        ),
    )

    assert reject_resp.status_code == 200, reject_resp.json()
    assert reject_resp.json()["status"] == "rejected"


def test_cancel_route_checks_sender_ledger_not_current_ledger_writer_role(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-cancel-route",
        ledger_id="receiver_cancel_route",
    )
    sender_account_id = _owner_account_id()
    _add_viewer_ledger(
        "sender_cancel_current_viewer",
        account_id=sender_account_id,
        owner_account_id=sender_account_id,
    )

    create_resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 2500},
    )
    assert create_resp.status_code == 200, create_resp.json()
    public_id = create_resp.json()["public_id"]

    cancel_resp = client.post(
        f"/api/bill-splits/{public_id}/cancel",
        headers=_bearer_for_account_ledger(
            sender_account_id,
            "sender_cancel_current_viewer",
        ),
    )

    assert cancel_resp.status_code == 200, cancel_resp.json()
    assert cancel_resp.json()["status"] == "cancelled"


def test_sender_expense_updates_do_not_change_receiver_snapshot() -> None:
    """ADR-0029: accepted receiver expenses are decoupled snapshots."""
    expense_id = _make_expense_for_owner(merchant="Original Merchant")
    receiver_account_id = _seed_receiver(
        name="B-isolated",
        ledger_id="receiver_isolated",
    )
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )
        _inv, received_expense = bsplit.accept_invitation(
            db,
            public_id=inv.public_id,
            accepting_account_id=receiver_account_id,
            target_ledger_id="receiver_isolated",
        )
        received_id = received_expense.id

    before = _expense_snapshot(received_id, "receiver_isolated")
    with SessionLocal() as db:
        sender_expense = db.scalar(
            select(Expense)
            .where(Expense.id == expense_id)
            .where(Expense.tenant_id == "owner")
        )
        assert sender_expense is not None
        sender_expense.merchant = "Sender Changed Merchant"
        sender_expense.note = "sender-only note"
        sender_expense.raw_text = "sender-only OCR text"
        sender_expense.image_path = "sender/changed.jpg"
        sender_expense.updated_at = now_utc()
        db.commit()

    after = _expense_snapshot(received_id, "receiver_isolated")
    assert after == before


def test_sender_cannot_invite_self(client: TestClient, *, identity) -> None:
    expense_id = _make_expense_for_owner()
    response = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": _owner_account_id(), "amount_cents": 2500},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_duplicate_pending_invite_to_same_receiver_rejected(
    client: TestClient, *, identity
) -> None:
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(name="B-dupe", ledger_id="receiver_dupe")
    first = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 2500},
    )
    assert first.status_code == 200, first.json()

    second = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": 2500},
    )
    assert second.status_code == 409
    assert second.json()["error"] == "split_invitation_already_pending"


def test_duplicate_pending_invite_integrity_error_maps_to_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB partial UNIQUE index is the race-proof duplicate guard."""
    expense_id = _make_expense_for_owner()
    receiver_account_id = _seed_receiver(
        name="B-dupe-integrity",
        ledger_id="receiver_dupe_integrity",
    )

    with SessionLocal() as db:
        bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_account_id,
            amount_cents=2500,
        )

    with SessionLocal() as db:
        original_scalar = db.scalar
        scalar_calls = 0

        def scalar_hiding_duplicate(statement, *args, **kwargs):
            nonlocal scalar_calls
            scalar_calls += 1
            if scalar_calls == 3:
                return None
            return original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", scalar_hiding_duplicate)

        with pytest.raises(AppError) as exc_info:
            bsplit.create_invitation(
                db,
                sender_account_id=_owner_account_id(),
                sender_ledger_id="owner",
                expense_id=expense_id,
                receiver_account_id=receiver_account_id,
                amount_cents=2500,
            )

        assert exc_info.value.error == "split_invitation_already_pending"
        assert exc_info.value.status_code == 409
        rows = list(
            db.scalars(
                select(BillSplitInvitation)
                .where(BillSplitInvitation.sender_expense_id == expense_id)
                .where(
                    BillSplitInvitation.receiver_account_id == receiver_account_id
                )
                .where(BillSplitInvitation.status == "invited")
            )
        )
        assert len(rows) == 1
