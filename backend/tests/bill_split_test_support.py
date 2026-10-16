"""Shared real database and HTTP setup for bilateral bill-split consumers."""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, AuthToken, Debt, Device, Expense, Ledger, LedgerMember
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.identity_service import hash_secret, new_session_token
from app.services.ledger_calendar_service import adopt_ledger_calendar
from app.services.time_service import now_utc
from tests._runtime_protocol import current_protocol_headers, negotiated_headers


def _split_headers(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    return negotiated_headers(client, {"Idempotency-Key": str(uuid4()), **headers})


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_receiver(
    name: str = "B", ledger_id: str = "receiver_b", *, ledger_name: str | None = None,
) -> int:
    """Create a second account + their own personal ledger where they are owner."""
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        ledger = Ledger(ledger_id=ledger_id, name=ledger_name or f"{name} 的账本", owner_account_id=account.id)
        db.add(ledger)
        db.flush()
        adopt_ledger_calendar(db, ledger_id=ledger_id, timezone_name="Asia/Shanghai", actor_account_id=account.id)
        member = LedgerMember(
            ledger_id=ledger_id,
            account_id=account.id,
            role="owner",
        )
        db.add(member)
        db.commit()
        return account.id


def _make_expense_for_owner(*, amount_cents: int = 5000, merchant: str = "Pizza Place") -> int:
    """Insert an expense into owner ledger directly (bypasses upload flow)."""
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            merchant=merchant,
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        refresh_legacy_expense_time(db, expense)
        db.add(expense)
        db.commit()
        return expense.id


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
    return current_protocol_headers({"Authorization": f"Bearer {token}"})


def _create_invited_split(
    client: TestClient,
    identity,
    receiver_account_id: int,
    *,
    amount_cents: int = 2500,
) -> str:
    """Owner sends a split invite to ``receiver_account_id``; return its public_id."""
    expense_id = _make_expense_for_owner()
    resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=_split_headers(client, identity.app_headers),
        json={"expected_row_version": 1, "receiver_account_id": receiver_account_id, "amount_cents": amount_cents},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["public_id"]


def _debts_for(public_id: str) -> list[Debt]:
    with SessionLocal() as db:
        return list(db.scalars(select(Debt).where(Debt.source_id == public_id)))


def _seed_web_receiver(ledger_id: str = "receiver_web", display: str = "B-web") -> tuple[int, str]:
    return _seed_receiver(display, ledger_id, ledger_name=f"{display} 账本"), ledger_id


def _make_web_expense(amount_cents: int = 4000) -> int:
    return _make_expense_for_owner(amount_cents=amount_cents, merchant="Pizza")
