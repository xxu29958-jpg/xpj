"""Personal relationship views must not replace the ledger-wide read contract."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Ledger, LedgerMember
from app.schemas import DebtCreateRequest
from app.services.debt_service import create_bill_split_debt, create_debt


def _owner_id() -> int:
    with SessionLocal() as db:
        account_id = db.scalar(
            select(LedgerMember.account_id).where(
                LedgerMember.ledger_id == "owner", LedgerMember.role == "owner"
            )
        )
        assert account_id is not None
        return account_id


def _member(name: str, ledger_id: str = "owner") -> int:
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        if ledger_id != "owner":
            db.add(Ledger(ledger_id=ledger_id, name=name, owner_account_id=account.id))
            db.flush()
        db.add(LedgerMember(
            ledger_id=ledger_id, account_id=account.id,
            role="owner" if ledger_id != "owner" else "member",
        ))
        db.commit()
        return account.id


def _external(account_id: int, label: str, direction: str) -> str:
    with SessionLocal() as db:
        return create_debt(
            db,
            tenant_id="owner",
            created_by_account_id=account_id,
            owner_account_id=account_id,
            payload=DebtCreateRequest(
                direction=direction,
                counterparty_type="external",
                counterparty_label=label,
                principal_amount_cents=500,
            ),
        ).public_id


def _split(debtor: int, creditor: int, ledger_id: str = "owner") -> str:
    with SessionLocal() as db:
        debt = create_bill_split_debt(
            db,
            ledger_id=ledger_id,
            receiver_account_id=debtor,
            sender_account_id=creditor,
            amount_cents=800,
            home_currency_code="CNY",
            source_invitation_public_id=str(uuid4()),
            event_time=None,
        )
        db.commit()
        return debt.public_id


def _rows(client: TestClient, identity, path: str) -> dict[str, dict]:
    response = client.get(path, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["home_currency_code"] == "CNY"
    rows = body["items"]
    assert len({row["public_id"] for row in rows}) == len(rows)
    return {row["public_id"]: row for row in rows}


def test_personal_external_lenses_leave_default_ledger_read_intact(client: TestClient, identity) -> None:
    owner = _owner_id()
    own_payable = _external(owner, "旅行", "i_owe")
    own_receivable = _external(owner, "演出票", "owed_to_me")
    others_payable = _external(_member("成员"), "成员记录的分期", "i_owe")

    assert set(_rows(client, identity, "/api/debts")) == {
        own_payable, own_receivable, others_payable,
    }
    assert set(_rows(client, identity, "/api/debts?lens=payables")) == {own_payable}
    assert set(_rows(client, identity, "/api/debts/receivables")) == {own_receivable}


def test_member_lenses_use_authenticated_participant_not_owner_relative_direction(
    client: TestClient, identity
) -> None:
    owner = _owner_id()
    other = _member("小林")
    third = _member("小周")
    payable = _split(owner, other)
    receivable = _split(other, owner)
    third_party = _split(other, third)

    payables = _rows(client, identity, "/api/debts?lens=payables")
    receivables = _rows(client, identity, "/api/debts/receivables")
    assert set(payables) == {payable}
    assert payables[payable]["viewer_is_debtor"] is True
    assert set(receivables) == {receivable}
    assert receivables[receivable]["viewer_is_debtor"] is False
    assert receivables[receivable]["counterparty_label"] == "小林"
    assert set(_rows(client, identity, "/api/debts")) == {payable, receivable, third_party}


def test_receivables_combine_local_and_cross_ledger_without_exposing_cross_ledger_identity(
    client: TestClient, identity
) -> None:
    owner = _owner_id()
    local = _split(_member("同账本成员"), owner)
    cross = _split(_member("另一账本成员", "personal_lens_other"), owner, "personal_lens_other")
    external = _external(owner, "演出票", "owed_to_me")

    rows = _rows(client, identity, "/api/debts/receivables")
    assert set(rows) == {local, cross, external}
    assert rows[local]["ledger_id"] == "owner"
    assert rows[cross]["ledger_id"] is None
    assert rows[cross]["counterparty_label"] == "另一账本成员"
    assert rows[cross]["viewer_is_debtor"] is False
