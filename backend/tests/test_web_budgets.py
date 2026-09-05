"""Tests for the v0.8 /web budget dashboard."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Budget, LedgerMember
from app.routes.web_app import _require_local as _web_require_local
from app.routes.web_budgets import _category_form_rows
from app.schemas import BudgetCategoryResponse, BudgetMonthlyResponse


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
            "excluded_category": ["医疗"],
            "excluded_categories": "报销",
            "category_budget_category": ["餐饮", "交通"],
            "category_budget_amount_yuan": ["100.00", "50.00"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def test_budget_presenter_keeps_fresh_execution_identity_when_draft_renames_row() -> None:
    fresh = BudgetMonthlyResponse(
        ledger_id="owner",
        month="2026-05",
        configured=True,
        total_amount_cents=100000,
        rollover_amount_cents=0,
        fixed_amount_cents=0,
        non_monthly_amount_cents=0,
        flex_budget_cents=100000,
        spent_amount_cents=12500,
        excluded_amount_cents=0,
        remaining_amount_cents=87500,
        overspent_amount_cents=0,
        excluded_categories=[],
        excluded_breakdown=[],
        category_budgets=[
            BudgetCategoryResponse(
                category="餐饮",
                amount_cents=10000,
                spent_amount_cents=12500,
                remaining_amount_cents=-2500,
                overspent_amount_cents=2500,
            )
        ],
    )

    row = _category_form_rows(
        fresh,
        currency_code="CNY",
        draft_categories=["购物"],
        draft_amounts=["101.00"],
    )[0]

    assert row["category"] == "购物"
    assert row["saved_category"] == "餐饮"
    assert row["spent_yuan"] == "125.00"
    assert row["remaining_yuan"] == "-25.00"
    assert row["overspent_yuan"] == "25.00"
    assert row["has_overspend"] is True


def test_web_budgets_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/budgets").status_code == 403
    assert client.post("/web/budgets/save").status_code == 403


def test_web_budgets_renders_unconfigured_state_and_nav(web_client: TestClient) -> None:
    response = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    start = re.search(r'<section[^>]+aria-label="开始设置预算"[^>]*>(.*?)</section>', response.text, re.S)
    assert start is not None
    assert 'action="/web/budgets/save"' in start.group(1)
    assert "本月已确认支出" in start.group(1)
    assert response.text.count('action="/web/budgets/save"') == 1
    assert "本月预算剩余" not in response.text
    assert "/web/budgets?ledger_id=owner" in response.text
    assert 'name="total_amount_yuan"' in response.text
    assert 'for="budget-total-amount-yuan"' in response.text
    assert 'id="budget-total-amount-yuan"' in response.text
    assert 'aria-label="分类预算金额"' in response.text
    assert response.text.count("data-budget-add-row") == 2
    assert "保存预算" in response.text
    options = re.search(r'<details[^>]+id="budget-options"([^>]*)>', response.text)
    assert options is not None
    # No-script form stays open; collapse is allowed only after the native
    # invalid-event reveal handler has been attached by budgets.js.
    assert "open" in options.group(1).split()
    assert 'data-start-expanded="false"' in options.group(1)
    assert '<summary hidden>' in response.text[options.end():]
    assert response.text.index('name="total_amount_yuan"') < options.start()
    options_end = response.text.index("</details>", options.end())
    assert response.text.index("保存预算</button>") > options_end
    for name in ("rollover_amount_yuan", "non_monthly_amount_yuan", "excluded_category", "category_budget_category"):
        assert f'name="{name}"' in response.text[options.end():options_end]


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
    assert "本月预算剩余" in page.text
    assert "¥925.00" in re.sub(r"<[^>]+>", "", page.text)
    assert "¥1000.00" in page.text
    assert "¥50.00" in page.text
    assert 'name="non_monthly_amount_yuan" value="120.00"' in page.text
    assert "餐饮" in page.text
    assert "超支 ¥25.00" in page.text
    assert "医疗 ¥30.00" in page.text
    assert re.search(r'<progress[^>]+value="12500"[^>]+max="105000"', page.text)
    assert page.text.count("<table") == 1
    assert "分类预算执行" not in page.text
    assert "Flex 可花" not in page.text
    assert "服务端预算" not in page.text
    assert page.text.count("data-budget-add-row") == 2
    assert page.text.count('name="category_budget_remove"') == 2
    assert re.search(r'<details[^>]+id="budget-options"[^>]*data-start-expanded="true"', page.text)


def test_first_budget_total_only_save_and_optional_error_remain_operable(web_client: TestClient) -> None:
    form = {
        "ledger_id": "owner",
        "month": "2026-05",
        "total_amount_yuan": "3000.00",
    }
    rejected = web_client.post(
        "/web/budgets/save",
        data={**form, "non_monthly_amount_yuan": "-1.00"},
    )
    assert rejected.status_code == 422
    assert _owner_budget_total() is None
    assert re.search(r'<details[^>]+id="budget-options"[^>]*data-start-expanded="true"', rejected.text)
    assert 'name="total_amount_yuan" value="3000.00"' in rejected.text
    assert 'name="non_monthly_amount_yuan" value="-1.00"' in rejected.text

    saved = web_client.post("/web/budgets/save", data=form, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    assert _owner_budget_total() == 300000


def test_web_budgets_viewer_read_only_and_post_denied(web_client: TestClient) -> None:
    _save_budget(web_client)
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    assert "只读角色" in page.text
    assert 'action="/web/budgets/save"' not in page.text
    assert "保存预算</button>" not in page.text
    assert 'name="category_budget_remove"' not in page.text

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
    assert "还没有本月预算" in response.text
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


def test_web_budgets_invalid_amount_shows_error_without_mutating(
    web_client: TestClient,
    *,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 12500,
            "merchant": "五月餐饮",
            "category": "餐饮",
            "expense_time": "2026-05-05T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    _save_budget(web_client)

    response = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "-1.00",
            "rollover_amount_yuan": "17.50",
            "non_monthly_amount_yuan": "222.00",
            "excluded_category": ["医疗"],
            "excluded_categories": "自定义",
            "category_budget_category": ["购物", "交通"],
            "category_budget_amount_yuan": ["101.00", ""],
            "category_budget_remove": ["0"],
        },
    )

    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert "预算没有保存" in response.text
    assert "月度总预算不能为负数" in response.text
    for value in ("-1.00", "17.50", "222.00", "101.00", "自定义", "购物"):
        assert f'value="{value}"' in response.text
    assert re.search(
        r'name="category_budget_remove"[^>]+value="0"[^>]+checked',
        response.text,
    )
    # 执行区仍来自未变更的 server snapshot，不能把 draft 冒充已保存预算。
    assert "本月预算剩余" in response.text
    visible_text = re.sub(r"<[^>]+>", "", response.text)
    assert "¥925.00" in visible_text
    assert "已保存：餐饮" in visible_text
    assert "超支 ¥25.00" in visible_text
    assert _owner_budget_total() == 100000


def test_web_budgets_too_long_category_preserves_full_draft(web_client: TestClient) -> None:
    _save_budget(web_client)
    too_long = "超" * 65

    response = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "1000.00",
            "rollover_amount_yuan": "17.50",
            "non_monthly_amount_yuan": "222.00",
            "excluded_category": ["医疗"],
            "excluded_categories": "自定义",
            "category_budget_category": [too_long, "交通"],
            "category_budget_amount_yuan": ["101.00", "55.00"],
            "category_budget_remove": ["1"],
        },
    )

    assert response.status_code == 422
    assert "分类名称过长，请缩短后再保存" in response.text
    for value in (too_long, "17.50", "222.00", "101.00", "55.00", "自定义"):
        assert f'value="{value}"' in response.text
    assert re.search(
        r'name="category_budget_remove"[^>]+value="1"[^>]+checked',
        response.text,
    )
    assert _owner_budget_total() == 100000


def test_web_budgets_combines_exclusions_and_removes_marked_category(
    web_client: TestClient,
    *,
    identity,
) -> None:
    _save_budget(web_client)

    response = web_client.post(
        "/web/budgets/save",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": "1000.00",
            "rollover_amount_yuan": "50.00",
            "non_monthly_amount_yuan": "120.00",
            "excluded_category": ["医疗"],
            "excluded_categories": "自定义",
            "category_budget_category": ["餐饮", "交通"],
            "category_budget_amount_yuan": ["100.00", "55.00"],
            "category_budget_remove": ["0"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    owner = web_client.get(
        "/api/budgets/monthly?month=2026-05",
        headers=identity.app_headers,
    )
    assert owner.status_code == 200, owner.text
    payload = owner.json()
    assert payload["excluded_categories"] == ["医疗", "自定义"]
    assert [(row["category"], row["amount_cents"]) for row in payload["category_budgets"]] == [("交通", 5500)]

    page = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    assert re.search(
        r'name="excluded_category"[^>]+value="医疗"[^>]+checked',
        page.text,
    )
    assert re.search(
        r'name="excluded_category"[^>]+value="自定义"[^>]+checked',
        page.text,
    )
