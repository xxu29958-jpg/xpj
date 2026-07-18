"""Viewer-relative payable/receivable topology for the Web product lens."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Account, Debt, Ledger, LedgerMember
from app.services.debt_service import (
    list_payables_for_account,
    list_receivables_for_account,
)


@dataclass(frozen=True)
class _LensExpectations:
    payable_ids: frozenset[str]
    receivable_ids: frozenset[str]


def _viewer_account_id(db: Session) -> int:
    account_id = db.scalar(
        select(LedgerMember.account_id)
        .where(LedgerMember.ledger_id == "owner")
        .order_by(LedgerMember.id.asc())
        .limit(1)
    )
    assert account_id is not None
    return account_id


def _add_debt(
    db: Session,
    *,
    owner_account_id: int,
    direction: str,
    counterparty_type: str,
    counterparty_account_id: int | None,
    label: str,
    tenant_id: str = "owner",
) -> Debt:
    debt = Debt(
        tenant_id=tenant_id,
        owner_account_id=owner_account_id,
        created_by_account_id=owner_account_id,
        direction=direction,
        counterparty_type=counterparty_type,
        counterparty_account_id=counterparty_account_id,
        counterparty_label=label,
        principal_amount_cents=10_000,
        home_currency_code="CNY",
        status="open",
        source_type="manual" if counterparty_type == "external" else "bill_split",
        source_id=None if counterparty_type == "external" else str(uuid4()),
    )
    db.add(debt)
    db.flush()
    return debt


def _seed_owner_ledger_debts(
    db: Session,
    viewer_id: int,
) -> tuple[Account, dict[str, Debt]]:
    peer = Account(display_name="关系对手方")
    third_owner = Account(display_name="第三方甲")
    third_counterparty = Account(display_name="第三方乙")
    db.add_all([peer, third_owner, third_counterparty])
    db.flush()
    debts = {
        "owner_payable_external": _add_debt(
            db,
            owner_account_id=viewer_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_account_id=None,
            label="我的信用卡",
        ),
        "owner_receivable_external": _add_debt(
            db,
            owner_account_id=viewer_id,
            direction="owed_to_me",
            counterparty_type="external",
            counterparty_account_id=None,
            label="我借出的款",
        ),
        "owner_payable_member": _add_debt(
            db,
            owner_account_id=viewer_id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=peer.id,
            label=peer.display_name,
        ),
        "owner_receivable_member": _add_debt(
            db,
            owner_account_id=viewer_id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=peer.id,
            label=peer.display_name,
        ),
        "counterparty_payable_member": _add_debt(
            db,
            owner_account_id=peer.id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=viewer_id,
            label="不应显示查看者自己",
        ),
        "counterparty_receivable_member": _add_debt(
            db,
            owner_account_id=peer.id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=viewer_id,
            label="不应显示查看者自己",
        ),
        "third_party": _add_debt(
            db,
            owner_account_id=third_owner.id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=third_counterparty.id,
            label=third_counterparty.display_name,
        ),
    }
    return peer, debts


def _seed_cross_ledger_receivable(
    db: Session,
    *,
    peer_id: int,
    viewer_id: int,
) -> Debt:
    ledger_id = f"personal-cross-{uuid4()}"
    db.add(
        Ledger(
            ledger_id=ledger_id,
            name="关系对手方账本",
            owner_account_id=peer_id,
        )
    )
    db.flush()
    db.add(
        LedgerMember(
            ledger_id=ledger_id,
            account_id=peer_id,
            role="owner",
        )
    )
    return _add_debt(
        db,
        tenant_id=ledger_id,
        owner_account_id=peer_id,
        direction="i_owe",
        counterparty_type="member",
        counterparty_account_id=viewer_id,
        label="不应显示查看者自己",
    )


def _assert_service_lenses(
    db: Session,
    *,
    viewer_id: int,
    peer_label: str,
    debts: dict[str, Debt],
    cross_ledger_receivable: Debt,
) -> _LensExpectations:
    payables = list_payables_for_account(
        db,
        tenant_id="owner",
        account_id=viewer_id,
    ).items
    receivables = list_receivables_for_account(
        db,
        tenant_id="owner",
        account_id=viewer_id,
    ).items
    payable_ids = frozenset(item.public_id for item in payables)
    receivable_ids = frozenset(item.public_id for item in receivables)
    assert payable_ids == frozenset(
        debts[key].public_id
        for key in (
            "owner_payable_external",
            "owner_payable_member",
            "counterparty_payable_member",
        )
    )
    assert receivable_ids == frozenset(
        [
            debts["owner_receivable_external"].public_id,
            debts["owner_receivable_member"].public_id,
            debts["counterparty_receivable_member"].public_id,
            cross_ledger_receivable.public_id,
        ]
    )
    all_rows = [*payables, *receivables]
    all_ids = [item.public_id for item in all_rows]
    assert debts["third_party"].public_id not in all_ids
    assert len(all_ids) == len(set(all_ids))
    mirrored_ids = {
        debts["counterparty_payable_member"].public_id,
        debts["counterparty_receivable_member"].public_id,
    }
    mirrored_rows = [item for item in all_rows if item.public_id in mirrored_ids]
    assert {item.counterparty_label for item in mirrored_rows} == {peer_label}
    return _LensExpectations(payable_ids, receivable_ids)


def _seed_and_assert_service_lenses() -> _LensExpectations:
    with SessionLocal() as db:
        viewer_id = _viewer_account_id(db)
        peer, debts = _seed_owner_ledger_debts(db, viewer_id)
        cross_ledger_receivable = _seed_cross_ledger_receivable(
            db,
            peer_id=peer.id,
            viewer_id=viewer_id,
        )
        db.commit()
        return _assert_service_lenses(
            db,
            viewer_id=viewer_id,
            peer_label=peer.display_name,
            debts=debts,
            cross_ledger_receivable=cross_ledger_receivable,
        )


def _assert_endpoint_lenses(
    client: TestClient,
    *,
    identity,
    expected: _LensExpectations,
) -> None:
    payable_response = client.get(
        "/api/debts/payables",
        headers=identity.app_headers,
    )
    receivable_response = client.get(
        "/api/debts/receivables",
        headers=identity.app_headers,
    )
    assert payable_response.status_code == 200, payable_response.json()
    assert receivable_response.status_code == 200, receivable_response.json()
    payable_ids = {
        item["public_id"] for item in payable_response.json()["items"]
    }
    assert payable_ids == expected.payable_ids
    endpoint_receivable_ids = [
        item["public_id"] for item in receivable_response.json()["items"]
    ]
    assert set(endpoint_receivable_ids) == expected.receivable_ids
    assert len(endpoint_receivable_ids) == len(set(endpoint_receivable_ids))


def test_personal_lens_endpoints_mirror_every_viewer_direction(
    client: TestClient,
    *,
    identity,
) -> None:
    expected = _seed_and_assert_service_lenses()
    _assert_endpoint_lenses(client, identity=identity, expected=expected)


def test_personal_lens_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/debts/payables").status_code == 401
    assert client.get("/api/debts/receivables").status_code == 401
