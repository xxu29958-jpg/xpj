"""Viewer and currency contracts for the Desktop product projection."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from _desktop_product_test_support import mint_desktop_token_from
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services._desktop_product_planning as desktop_planning
from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, AuthToken, Debt, Device, LedgerMember
from app.routes import desktop_product as desktop_product_routes
from app.services.identity_service import hash_secret, new_session_token
from app.services.time_service import now_utc

_BRIDGE_HEADERS = {"X-Ticketbox-Desktop-Bridge": "v1"}


def _principal_headers(token: str) -> dict[str, str]:
    return {
        **_BRIDGE_HEADERS,
        "Authorization": f"Bearer {token}",
    }


def _mint_ledger_member(
    *,
    display_name: str,
    role: str = "member",
) -> tuple[int, str]:
    with SessionLocal() as db:
        account = Account(display_name=display_name)
        db.add(account)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id="owner",
                account_id=account.id,
                role=role,
            )
        )
        device = Device(
            account_id=account.id,
            device_name=f"pytest-{display_name}",
            platform="desktop",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id="owner",
                scope="app",
            )
        )
        db.commit()
        return account.id, token


def _workspace(
    client: TestClient,
    workspace: str,
    *,
    token: str,
) -> dict:
    response = client.get(
        f"/desktop/workspaces/{workspace}",
        headers=_principal_headers(token),
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _seed_obligation_contract() -> tuple[dict[str, str], str, str]:
    member_id, member_token = _mint_ledger_member(display_name="家人乙")
    _, third_token = _mint_ledger_member(display_name="家人丙")
    with SessionLocal() as db:
        owner_id = db.scalar(
            select(LedgerMember.account_id).where(
                LedgerMember.ledger_id == "owner",
                LedgerMember.role == "owner",
            )
        )
        assert owner_id is not None
        owner_external = Debt(
            tenant_id="owner",
            owner_account_id=owner_id,
            created_by_account_id=owner_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_label="我的美元卡",
            principal_amount_cents=1234,
            home_currency_code="USD",
            source_type="manual",
        )
        member_external = Debt(
            tenant_id="owner",
            owner_account_id=member_id,
            created_by_account_id=member_id,
            direction="owed_to_me",
            counterparty_type="external",
            counterparty_label="家人乙的借出",
            principal_amount_cents=8800,
            home_currency_code="CNY",
            source_type="manual",
        )
        shared = Debt(
            tenant_id="owner",
            owner_account_id=owner_id,
            created_by_account_id=owner_id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=member_id,
            counterparty_label="家人乙",
            principal_amount_cents=6600,
            home_currency_code="CNY",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add_all([owner_external, member_external, shared])
        db.commit()
        return (
            {
                "owner_external": owner_external.public_id,
                "member_external": member_external.public_id,
                "shared": shared.public_id,
            },
            member_token,
            third_token,
        )


def test_desktop_obligations_are_personal_and_viewer_role_authoritative(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    monkeypatch.setattr(
        desktop_product_routes,
        "require_owner_console_local",
        lambda _request: None,
    )
    ids, member_token, third_token = _seed_obligation_contract()
    owner_token = mint_desktop_token_from(identity.app_token)
    owner_rows = {
        row["key"].removeprefix("debt:"): row
        for row in _workspace(
            client,
            "obligations",
            token=owner_token,
        )["rows"]
    }
    member_rows = {
        row["key"].removeprefix("debt:"): row
        for row in _workspace(
            client,
            "obligations",
            token=member_token,
        )["rows"]
    }
    third_rows = _workspace(client, "obligations", token=third_token)["rows"]

    assert set(owner_rows) == {ids["owner_external"], ids["shared"]}
    assert owner_rows[ids["owner_external"]]["subtitle"] == "我的应付"
    assert owner_rows[ids["owner_external"]]["currency_code"] == "USD"
    assert owner_rows[ids["shared"]]["subtitle"] == "你帮我垫的"
    assert set(member_rows) == {ids["member_external"], ids["shared"]}
    assert member_rows[ids["member_external"]]["subtitle"] == "我的应收"
    assert member_rows[ids["shared"]]["subtitle"] == "我帮你垫的"
    assert third_rows == []


def _stub_budget_goal_and_income(monkeypatch, now) -> None:
    monkeypatch.setattr(desktop_planning, "current_month", lambda _timezone: "2026-07")
    monkeypatch.setattr(
        desktop_planning,
        "get_monthly_budget",
        lambda *_args, **_kwargs: SimpleNamespace(
            configured=True,
            total_amount_cents=1234,
            spent_amount_cents=1234,
            remaining_amount_cents=1234,
            fixed_amount_cents=1234,
            non_monthly_amount_cents=1234,
            updated_at=now,
        ),
    )
    monkeypatch.setattr(
        desktop_planning,
        "list_goals",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                public_id="goal-currency",
                name="货币目标",
                category=None,
                progress_state="on_track",
                progress_percent=25,
                target_amount_cents=1234,
                spent_amount_cents=1234,
                remaining_amount_cents=1234,
                status="active",
                updated_at=now,
            )
        ],
    )
    monkeypatch.setattr(
        desktop_planning,
        "list_income_plans",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                public_id="income-currency",
                label="工资",
                source_type="salary",
                frequency="monthly",
                status="active",
                amount_cents=1234,
                updated_at=now,
                income_month=None,
                pay_day=10,
            )
        ],
    )


def _stub_recurring_and_insights(monkeypatch, now) -> None:
    monkeypatch.setattr(
        desktop_planning,
        "list_recurring_items",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                public_id="recurring-currency",
                merchant_name="固定支出",
                status="active",
                baseline_amount_cents=1234,
                last_amount_cents=1234,
                occurrence_count=3,
                next_expected_date=None,
                updated_at=now,
                confidence="high",
            )
        ],
    )
    monkeypatch.setattr(
        desktop_planning,
        "data_quality_summary",
        lambda *_args, **_kwargs: SimpleNamespace(
            generated_at=now,
            missing_amount=0,
            missing_merchant=0,
            suspected_duplicates=0,
            confirmed_without_image=0,
        ),
    )
    monkeypatch.setattr(
        desktop_planning,
        "reports_overview",
        lambda *_args, **_kwargs: {
            "count": 2,
            "total_amount_cents": 1234,
            "previous_total_amount_cents": 1234,
            "year_over_year_total_amount_cents": 1234,
        },
    )


@pytest.mark.parametrize(
    ("currency_code", "formatted"),
    [
        pytest.param("JPY", "¥1,234", id="jpy-zero-fraction"),
        pytest.param("USD", "$12.34", id="usd-two-fraction"),
    ],
)
def test_desktop_plans_and_insights_use_configured_home_currency(
    client: TestClient,
    monkeypatch,
    identity,
    currency_code: str,
    formatted: str,
) -> None:
    monkeypatch.setattr(
        desktop_product_routes,
        "require_owner_console_local",
        lambda _request: None,
    )
    now = now_utc()
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
    get_settings.cache_clear()
    _stub_budget_goal_and_income(monkeypatch, now)
    _stub_recurring_and_insights(monkeypatch, now)
    desktop_token = mint_desktop_token_from(identity.app_token)

    try:
        plan_rows = _workspace(
            client,
            "plans",
            token=desktop_token,
        )["rows"]
        insight_rows = _workspace(
            client,
            "insights",
            token=desktop_token,
        )["rows"]
    finally:
        get_settings.cache_clear()

    by_kind = {row["kind"]: row for row in plan_rows}
    assert set(by_kind) == {"budget", "goal", "income", "recurring"}
    for row in by_kind.values():
        assert row["currency_code"] == currency_code
        assert row["amount_minor"] == 1234
    assert formatted in by_kind["budget"]["subtitle"]
    assert any(field["value"] == formatted for field in by_kind["goal"]["fields"])
    assert any(field["value"] == formatted for field in by_kind["recurring"]["fields"])
    report = next(row for row in insight_rows if row["kind"] == "report_summary")
    assert report["currency_code"] == currency_code
    assert report["amount_minor"] == 1234
    assert any(field["value"] == formatted for field in report["fields"])
