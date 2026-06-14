"""Shared fixtures for ADR-0049 member repayment proposal tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Account,
    AuthToken,
    Debt,
    Device,
    ExchangeRate,
    LedgerMember,
)
from app.services.identity_service import hash_secret, new_session_token

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _seed_usd_rate(*, tenant_id: str, rate_date: date, rate_to_cny: str) -> None:
    """Seed one USD→CNY rate snapshot (mirrors ``test_debt_repayment._seed_usd_rate``)."""
    with SessionLocal() as db:
        db.add(
            ExchangeRate(
                tenant_id=tenant_id,
                currency_code="USD",
                rate_date=rate_date,
                rate_to_cny=Decimal(rate_to_cny),
                source="manual",
            )
        )
        db.commit()


def _mint_member_actor(*, ledger_id: str = "owner", role: str = "member") -> tuple[int, str]:
    """Create a SECOND authed account in ``ledger_id`` and return (account_id, app_token).

    Models a distinct family member: its own Account, a writer ``LedgerMember``
    row in the same ledger (so it is a writer, not just a bare account), a Device,
    and an app-scope AuthToken — the minimum the auth chain needs to resolve a
    full ``AuthContext`` (account/device/ledger/role) for this actor.
    """
    with SessionLocal() as db:
        account = Account(display_name="家人")
        db.add(account)
        db.flush()
        db.add(
            LedgerMember(ledger_id=ledger_id, account_id=account.id, role=role)
        )
        device = Device(
            account_id=account.id, device_name="pytest-member", platform="android"
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
        return account.id, token


def _member_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_member_debt(
    client: TestClient,
    headers: dict[str, str],
    *,
    direction: str,
    member_account_id: int,
    principal_amount_cents: int = 50000,
) -> dict:
    """Seed a committed member Debt directly.

    Public ``POST /api/debts`` only creates external Debt now (ADR-0049 §5.2: a
    member obligation needs the affected party's confirmation before it is
    committed — it arrives via bill_split accept in slice 4, or this direct seed
    in tests). ``direction='owed_to_me'`` → debtor=member, creditor=owner (the
    member proposes, the owner confirms); ``direction='i_owe'`` → the mirror.
    ``client`` / ``headers`` are kept for call-site symmetry with the external
    helper but unused (the seed writes the row directly).
    """
    del client, headers
    with SessionLocal() as db:
        owner_account_id = db.scalar(
            select(Account.id).order_by(Account.id.asc()).limit(1)
        )
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction=direction,
            counterparty_type="member",
            counterparty_account_id=member_account_id,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return {"public_id": debt.public_id, "row_version": debt.row_version}


def _create_external_debt(
    client: TestClient, headers: dict[str, str], *, principal_amount_cents: int = 50000
) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "招商信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _propose(
    client: TestClient,
    headers: dict[str, str],
    debt_public_id: str,
    *,
    proposed_amount_cents: int,
    **extra: object,
):
    return client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(headers),
        json={"proposed_amount_cents": proposed_amount_cents, **extra},
    )


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _propose_foreign(
    client: TestClient,
    headers: dict[str, str],
    debt_public_id: str,
    *,
    original_currency_code: str,
    original_amount: str,
    paid_at: str,
):
    """Create a foreign-currency proposal (no proposed_amount_cents — the two
    amount inputs are mutually exclusive; the backend freezes the home amount)."""
    return client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(headers),
        json={
            "original_currency_code": original_currency_code,
            "original_amount": original_amount,
            "paid_at": paid_at,
        },
    )
