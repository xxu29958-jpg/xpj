"""C3a action settlement regressions on the exact Web debt detail surface."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember


def _api_headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_external_debt(web_client: TestClient, *, identity) -> dict:
    response = web_client.post(
        "/api/debts",
        headers=_api_headers(identity),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "测试信用卡",
            "principal_amount_cents": 10_000,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_open_member_debt_for_owner_debtor() -> tuple[str, int]:
    with SessionLocal() as db:
        owner_id = db.scalar(
            select(LedgerMember.account_id).where(
                LedgerMember.ledger_id == "owner",
                LedgerMember.role == "owner",
            )
        )
        assert owner_id is not None
        creditor = Account(display_name="家人")
        db.add(creditor)
        db.flush()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_id,
            created_by_account_id=owner_id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=creditor.id,
            principal_amount_cents=20_000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id, debt.row_version


def test_terminal_conflict_keeps_honest_attempt_receipt(
    web_client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(web_client, identity=identity)
    cleared = web_client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_api_headers(identity),
        json={
            "amount_cents": 10_000,
            "expected_row_version": debt["row_version"],
        },
    )
    assert cleared.status_code == 201, cleared.text

    stale = web_client.post(
        f"/web/debts/{debt['public_id']}/repayments",
        data={
            "csrf_token": "test-client-bypasses-middleware-check",
            "ledger_id": "owner",
            "expected_row_version": str(debt["row_version"]),
            "idempotency_key": str(uuid4()),
            "amount_major": "20.00",
            "paid_at": "2026-07-19",
        },
    )

    assert stale.status_code == 409
    assert 'role="alert"' in stale.text
    assert "20.00" in stale.text
    assert "2026-07-19" in stale.text
    assert "已结清" in stale.text
    assert "你填写的内容还在" not in stale.text
    assert f'action="/web/debts/{debt["public_id"]}/repayments"' not in stale.text
    current = web_client.get(
        f"/api/debts/{debt['public_id']}",
        headers=identity.app_headers,
    )
    assert current.status_code == 200
    assert current.json()["paid_amount_cents"] == 10_000


def test_open_member_debt_owner_can_reach_kind_correction(
    web_client: TestClient,
) -> None:
    public_id, row_version = _seed_open_member_debt_for_owner_debtor()

    page = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")

    assert page.status_code == 200
    assert f'action="/web/debts/{public_id}/kind"' in page.text
    assert f'action="/web/debts/{public_id}/repayments"' not in page.text
    assert f'action="/web/debts/{public_id}/adjustments"' not in page.text
    assert f'action="/web/debts/{public_id}/void"' not in page.text
    assert f'action="/web/debts/{public_id}/forgive"' not in page.text

    changed = web_client.post(
        f"/web/debts/{public_id}/kind",
        data={
            "csrf_token": "test-client-bypasses-middleware-check",
            "ledger_id": "owner",
            "expected_row_version": str(row_version),
            "idempotency_key": str(uuid4()),
            "debt_kind": "revolving",
        },
    )
    assert changed.status_code == 200
    assert "还款类型已更新" in changed.text
    with SessionLocal() as db:
        stored = db.scalar(select(Debt).where(Debt.public_id == public_id))
        assert stored is not None
        assert stored.debt_kind == "revolving"
