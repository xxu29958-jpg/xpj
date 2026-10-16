"""Shared debt API preparation for repayments, captured drafts and proposals."""

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
    Ledger,
    LedgerMember,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.identity_service import hash_secret, new_session_token
from tests._runtime_protocol import current_protocol_headers, negotiated_headers

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _seed_usd_rate(*, tenant_id: str, rate_date: date, rate_to_cny: str) -> None:
    """Seed one USD→CNY rate snapshot through the existing currency authority."""
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(
            ExchangeRate(
                tenant_id=tenant_id,
                home_currency_code="CNY",
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
    return current_protocol_headers({"Authorization": f"Bearer {token}"})


def _create_member_debt(
    client: TestClient,
    headers: dict[str, str],
    *,
    direction: str,
    member_account_id: int,
    ledger_id: str = "owner",
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
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == ledger_id)
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert owner_account_id is not None
        debt = Debt(
            tenant_id=ledger_id,
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
        resolve_write_capability(db)
        db.add(debt)
        db.commit()
        return {"public_id": debt.public_id, "row_version": debt.row_version}


def _create_external_debt(
    client: TestClient, headers: dict[str, str], *, principal_amount_cents: int = 50000,
    counterparty_label: str = "招商信用卡",
) -> dict:
    response = client.post(
        "/api/debts",
        headers=negotiated_headers(client, _idem(headers)),
        json={
            "home_currency_code": "CNY", "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": counterparty_label,
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


def _owner_account_id() -> int:
    with SessionLocal() as db:
        account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert account_id is not None
        return account_id



def _record_repayment(
    client: TestClient,
    headers: dict[str, str],
    debt: dict,
    *,
    amount_cents: int,
) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(headers),
        json={
            "amount_cents": amount_cents,
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()



def _void_repayment(
    client: TestClient,
    headers: dict[str, str],
    debt: dict,
    *,
    repayment_public_id: str,
    reason: str,
) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(headers),
        json={
            "repayment_public_id": repayment_public_id,
            "reason": reason,
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()



def _seed_cross_ledger_member_debt() -> tuple[str, str]:
    """Return ``(debt_public_id, debtor_token)`` for owner-as-creditor."""
    creditor_id = _owner_account_id()
    with SessionLocal() as db:
        debtor = Account(display_name="跨账本债务人")
        db.add(debtor)
        db.flush()
        ledger_id = f"debtor-{uuid4()}"
        db.add(
            Ledger(
                ledger_id=ledger_id,
                name="债务人的私人账本",
                owner_account_id=debtor.id,
            )
        )
        db.add(
            LedgerMember(
                ledger_id=ledger_id,
                account_id=debtor.id,
                role="owner",
            )
        )
        device = Device(
            account_id=debtor.id,
            device_name="pytest-cross-ledger-debtor",
            platform="android",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=debtor.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        debt = Debt(
            tenant_id=ledger_id,
            owner_account_id=debtor.id,
            created_by_account_id=debtor.id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=creditor_id,
            principal_amount_cents=4_000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id, token


def capture_repayment_draft(
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
