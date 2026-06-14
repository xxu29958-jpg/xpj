"""ADR-0049 Debt domain slice 1: external/manual Debt create / list / get.

Pins the §11 confirmation subset that slice 1 owns: principal frozen at create,
remaining/paid derived (remaining == principal for a fresh Debt), ledger scope,
viewer cannot create (§5/§11 → backend 403), foreign-currency principal frozen
from the [[0027]] snapshot (pending → 409), ``extra='forbid'`` on the request,
and the [[0042]] Idempotency-Key replay contract.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, ExchangeRate, LedgerMember

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem_headers(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _seed_member_account(name: str = "家人") -> int:
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.commit()
        return account.id


def _seed_usd_rate(*, tenant_id: str, rate_date: date, rate_to_cny: str) -> None:
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


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def test_create_external_debt_freezes_home_principal(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "招商信用卡",
            "principal_amount_cents": 50000,
        },
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["direction"] == "i_owe"
    assert body["counterparty_type"] == "external"
    assert body["counterparty_label"] == "招商信用卡"
    assert body["counterparty_account_id"] is None
    assert body["principal_amount_cents"] == 50000
    # Fresh Debt: empty fact tables → remaining == principal, paid == 0, open.
    assert body["remaining_amount_cents"] == 50000
    assert body["paid_amount_cents"] == 0
    assert body["status"] == "open"
    assert body["source_type"] == "manual"
    assert body["source_id"] is None
    assert body["home_currency_code"] == "CNY"
    assert body["row_version"] == 1
    assert body["public_id"]


def test_create_member_debt_is_deferred_to_confirmation_flow(
    client: TestClient, *, identity
) -> None:
    member_account_id = _seed_member_account()
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "owed_to_me",
            "counterparty_type": "member",
            "counterparty_account_id": member_account_id,
            "principal_amount_cents": 12000,
        },
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_counterparty_invalid"

    # Member Debt without an account id is still incomplete, and the public
    # committed-create path remains closed until the confirmation flow lands.
    missing = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "owed_to_me",
            "counterparty_type": "member",
            "principal_amount_cents": 12000,
        },
    )
    assert missing.status_code == 422
    assert missing.json()["error"] == "debt_counterparty_invalid"


def test_list_debts_is_ledger_scoped(client: TestClient, *, identity) -> None:
    owner = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "房东",
            "principal_amount_cents": 30000,
        },
    )
    assert owner.status_code == 201, owner.json()
    gray = client.post(
        "/api/debts",
        headers=_idem_headers(identity.gray_app_headers),
        json={
            "direction": "owed_to_me",
            "counterparty_type": "external",
            "counterparty_label": "同事",
            "principal_amount_cents": 8000,
        },
    )
    assert gray.status_code == 201, gray.json()

    owner_list = client.get("/api/debts", headers=identity.app_headers)
    assert owner_list.status_code == 200, owner_list.json()
    owner_labels = [item["counterparty_label"] for item in owner_list.json()["items"]]
    assert owner_labels == ["房东"]

    gray_list = client.get("/api/debts", headers=identity.gray_app_headers)
    assert gray_list.status_code == 200, gray_list.json()
    gray_labels = [item["counterparty_label"] for item in gray_list.json()["items"]]
    assert gray_labels == ["同事"]


def test_get_debt_by_public_id_and_cross_ledger_404(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "花呗",
            "principal_amount_cents": 9900,
        },
    )
    assert created.status_code == 201, created.json()
    public_id = created.json()["public_id"]

    detail = client.get(f"/api/debts/{public_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["public_id"] == public_id
    assert detail.json()["remaining_amount_cents"] == 9900

    # The other ledger cannot see this Debt (existence-hiding 404).
    cross = client.get(f"/api/debts/{public_id}", headers=identity.gray_app_headers)
    assert cross.status_code == 404
    assert cross.json()["error"] == "debt_not_found"

    missing = client.get("/api/debts/does-not-exist", headers=identity.app_headers)
    assert missing.status_code == 404
    assert missing.json()["error"] == "debt_not_found"


def test_viewer_cannot_create_debt(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    _set_owner_ledger_role("viewer")
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "只读不能写",
            "principal_amount_cents": 10000,
        },
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_foreign_currency_debt_pending_rate_is_rejected(client: TestClient, *, identity) -> None:
    # No USD rate seeded for the event date → backend cannot freeze a home
    # principal → reject rather than commit an un-foldable Debt (§2.2).
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "美元借款",
            "original_currency": "USD",
            "original_amount": "100.00",
            "event_time": "2026-05-10T04:00:00Z",
        },
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "exchange_rate_pending"


def test_foreign_currency_debt_freezes_home_principal_from_snapshot(
    client: TestClient, *, identity
) -> None:
    # 2026-05-10T04:00Z falls on the Asia/Shanghai accounting date 2026-05-10.
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "美元借款",
            "original_currency": "USD",
            "original_amount": "100.00",
            "event_time": "2026-05-10T04:00:00Z",
        },
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    # 100 USD * 7.2 = 720.00 CNY → 72000 home cents, frozen.
    assert body["principal_amount_cents"] == 72000
    assert body["remaining_amount_cents"] == 72000
    assert body["home_currency_code"] == "CNY"
    assert body["original_currency_code"] == "USD"
    assert body["original_amount_minor"] == 10000
    assert Decimal(str(body["exchange_rate_to_cny"])) == Decimal("7.2")


def test_create_debt_rejects_unknown_field(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "未知字段",
            "principal_amount_cents": 1000,
            "remaining_amount_cents": 0,  # derived — must not be settable
        },
    )
    assert response.status_code == 422, response.json()


def test_create_debt_requires_idempotency_key(client: TestClient, *, identity) -> None:
    # coverage: auth-401
    response = client.post(
        "/api/debts",
        headers=identity.app_headers,  # no Idempotency-Key header
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "缺幂等键",
            "principal_amount_cents": 1000,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_create_debt_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "未登录",
            "principal_amount_cents": 1000,
        },
    )
    assert response.status_code == 401


def test_create_debt_idempotent_replay_and_fingerprint_mismatch(
    client: TestClient, *, identity
) -> None:
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {
        "direction": "i_owe",
        "counterparty_type": "external",
        "counterparty_label": "重试一次",
        "principal_amount_cents": 4500,
    }
    first = client.post("/api/debts", headers=headers, json=payload)
    assert first.status_code == 201, first.json()
    public_id = first.json()["public_id"]

    # Same key + same fingerprint → the same committed Debt, not a second row
    # (assert against the rendered response, not a DB peek).
    replay = client.post("/api/debts", headers=headers, json=payload)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == public_id

    listed = client.get("/api/debts", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert len(listed.json()["items"]) == 1

    # Same key + different request → reuse is rejected.
    mismatch = client.post(
        "/api/debts",
        headers=headers,
        json={**payload, "principal_amount_cents": 9999},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"] == "idempotency_key_reused"
