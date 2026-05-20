"""Tests for the v0.8 /web budget dashboard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Budget, LedgerMember
from app.routes.web_app import _require_local as _web_require_local

@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def _owner_budget_total() -> int | None:
    with SessionLocal() as db:
        return db.scalar(select(Budget.total_amount_cents).where(Budget.tenant_id == "owner"))


def _save_budget(web_client: TestClient, *, total: str = "1000.00") -> None:
    response = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": total,
            "rollover_amount_yuan": "50.00",
            "non_monthly_amount_yuan": "120.00",
            "excluded_categories": "医疗, 报销",
            "category_budget_category": ["餐饮", "交通"],
            "category_budget_amount_yuan": ["100.00", "50.00"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def test_web_budgets_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/budgets").status_code == 403
    assert client.post("/web/budgets/save").status_code == 403


def test_web_budgets_renders_unconfigured_state_and_nav(web_client: TestClient) -> None:
    response = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    assert "预算" in response.text
    assert "未配置" in response.text
    assert "/web/budgets?ledger_id=owner" in response.text
    assert 'name="total_amount_yuan"' in response.text
    assert "保存预算" in response.text


def test_web_budgets_save_and_display_budget_dashboard(web_client: TestClient, *, identity) -> None:
    web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 12500,
            "merchant": "五月餐饮",
            "category": "餐饮",
            "expense_time": "2026-05-05T12:00:00Z",
        },
    )
    web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 3000,
            "merchant": "医保报销",
            "category": "医疗",
            "expense_time": "2026-05-06T12:00:00Z",
        },
    )

    _save_budget(web_client)

    page = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    assert "¥1000.00" in page.text
    assert "¥50.00" in page.text
    assert 'name="non_monthly_amount_yuan" value="120.00"' in page.text
    assert "餐饮" in page.text
    assert "超支 ¥25.00" in page.text
    assert "医疗 ¥30.00" in page.text


def test_web_budgets_viewer_read_only_and_post_denied(web_client: TestClient) -> None:
    _save_budget(web_client)
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    assert "只读角色" in page.text
    assert 'action="/web/budgets/save"' not in page.text
    assert "保存预算</button>" not in page.text

    denied = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "2000.00",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"
    assert _owner_budget_total() == 100000


def test_web_budgets_selected_ledger_isolated(web_client: TestClient, *, identity) -> None:
    _save_budget(web_client)
    response = web_client.get("/web/budgets?ledger_id=tester_1&month=2026-05")

    assert response.status_code == 200
    assert "灰度用户1" in response.text
    assert "未配置" in response.text
    assert "¥1000.00" not in response.text

    gray_expense = web_client.post(
        "/api/expenses/manual",
        headers=identity.gray_app_headers,
        json={
            "amount_cents": 6600,
            "merchant": "灰度餐饮",
            "category": "餐饮",
            "expense_time": "2026-05-05T12:00:00Z",
        },
    )
    assert gray_expense.status_code == 200
    gray_page = web_client.get("/web/budgets?ledger_id=tester_1&month=2026-05")
    assert gray_page.status_code == 200
    assert "¥66.00" in gray_page.text


def test_web_budgets_invalid_amount_shows_error_without_mutating(web_client: TestClient) -> None:
    _save_budget(web_client)

    response = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "-1.00",
        },
    )

    assert response.status_code == 200
    assert "月度总预算不能为负数" in response.text
    assert _owner_budget_total() == 100000
