"""Independent Web product closure for manual entry and plan/catalog edits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local as _web_require_local
from tests.test_web_edge_runtime_contract import _discover_edge, _edge_cdp


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_web_manual_expense_is_idempotent_and_opens_detail(
    web_client: TestClient,
    *,
    identity,
) -> None:
    page = web_client.get("/web/expenses/new?ledger_id=owner")
    assert page.status_code == 200
    assert "金额（CNY" in page.text
    client_ref = re.search(r'name="client_ref" value="([^"]+)"', page.text)
    assert client_ref is not None
    payload = {
        "ledger_id": "owner",
        "amount_yuan": "36.80",
        "currency_code": "CNY",
        "expense_time": "2026-07-18T12:30",
        "merchant": "Web 手工商户",
        "category": "餐饮",
        "tags": "工作, 午餐",
        "note": "字段回显与幂等测试",
        "client_ref": client_ref.group(1),
    }
    first = web_client.post("/web/expenses/new", data=payload, follow_redirects=False)
    second = web_client.post("/web/expenses/new", data=payload, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    detail = web_client.get(first.headers["location"])
    assert detail.status_code == 200
    assert "Web 手工商户" in detail.text


def test_web_manual_expense_error_preserves_fields(
    web_client: TestClient,
    *,
    identity,
) -> None:
    response = web_client.post(
        "/web/expenses/new",
        data={
            "ledger_id": "owner",
            "amount_yuan": "0",
            "currency_code": "CNY",
            "expense_time": "2026-07-18T12:30",
            "merchant": "保留我",
            "client_ref": "web-manual-error",
        },
    )
    assert response.status_code == 422
    assert 'value="保留我"' in response.text
    assert "金额必须大于 0" in response.text


def test_web_category_preference_delete_preserves_history_and_enters_recycle_bin(
    web_client: TestClient,
    *,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1200,
            "merchant": "分类历史",
            "category": "手冲咖啡",
            "client_ref": "web-category-delete",
        },
    )
    assert created.status_code == 200
    preferences = web_client.get(
        "/api/expenses/categories/preferences",
        headers=identity.app_headers,
    ).json()["items"]
    item = next(row for row in preferences if row["name"] == "手冲咖啡")
    page = web_client.get("/web/categories?ledger_id=owner")
    assert f"/web/categories/preferences/{item['public_id']}/delete" in page.text
    deleted = web_client.post(
        f"/web/categories/preferences/{item['public_id']}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": item["row_version"],
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    historical = web_client.get(
        f"/api/expenses/{created.json()['id']}",
        headers=identity.app_headers,
    )
    assert historical.json()["category"] == "手冲咖啡"
    recycle = web_client.get("/web/recycle-bin?ledger_id=owner")
    assert recycle.status_code == 200
    assert "手冲咖啡" in recycle.text


def test_web_spending_goal_edit_uses_occ(web_client: TestClient, *, identity) -> None:
    created = web_client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": "原目标",
            "month": "2026-07",
            "target_amount_cents": 50000,
            "category": "餐饮",
        },
    ).json()
    payload = {
        "ledger_id": "owner",
        "month": "2026-07",
        "name": "更新目标",
        "target_amount_yuan": "600.00",
        "category": "餐饮",
        "expected_row_version": created["row_version"],
    }
    updated = web_client.post(
        f"/web/goals/{created['public_id']}/edit",
        data=payload,
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert "更新目标" in web_client.get(updated.headers["location"]).text
    stale = web_client.post(
        f"/web/goals/{created['public_id']}/edit",
        data=payload,
        follow_redirects=True,
    )
    assert "页面已过期" in stale.text


def test_web_income_plan_edit_uses_occ(web_client: TestClient, *, identity) -> None:
    created = web_client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "原收入",
            "source_type": "salary",
            "frequency": "monthly",
            "amount_cents": 100000,
            "pay_day": 10,
        },
    ).json()
    payload = {
        "ledger_id": "owner",
        "expected_row_version": created["row_version"],
        "label": "更新收入",
        "source_type": "bonus",
        "frequency": "one_time",
        "income_month_year": "2026",
        "income_month_number": "8",
        "amount_yuan": "1200.00",
        "pay_day": "18",
    }
    updated = web_client.post(
        f"/web/income-plans/{created['public_id']}/edit",
        data=payload,
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert "更新收入" in web_client.get(updated.headers["location"]).text
    stale = web_client.post(
        f"/web/income-plans/{created['public_id']}/edit",
        data=payload,
        follow_redirects=True,
    )
    assert "页面已过期" in stale.text


def test_web_manual_expense_main_path_renders_in_real_edge(
    web_client: TestClient,
    *,
    identity,
    tmp_path: Path,
) -> None:
    response = web_client.get("/web/expenses/new?ledger_id=owner")
    assert response.status_code == 200
    static_uri = (Path(__file__).resolve().parents[1] / "app" / "static").as_uri()
    rendered = response.text.replace('"/static/', f'"{static_uri}/')
    page = tmp_path / "manual-expense.html"
    page.write_text(rendered, encoding="utf-8")
    value = _edge_cdp().evaluate_page(
        _discover_edge(),
        profile=tmp_path / "edge-manual-expense",
        url=page.as_uri(),
        width=1440,
        height=900,
        expression="""document.readyState === "complete" ? (() => {
          const form = document.querySelector('form[action="/web/expenses/new"]');
          const amount = form?.querySelector('[name="amount_yuan"]');
          const submit = form?.querySelector('button[type="submit"]');
          const rect = submit?.getBoundingClientRect();
          return {
            title: document.querySelector("h1")?.textContent.trim(),
            hasForm: Boolean(form),
            fieldCount: form?.querySelectorAll("input, textarea").length || 0,
            currencyText: amount?.closest("label")?.textContent || "",
            submitWidth: rect?.width || 0,
            submitHeight: rect?.height || 0,
            horizontalOverflow: document.documentElement.scrollWidth > innerWidth
          };
        })() : undefined""",
    )
    assert isinstance(value, dict)
    assert value["title"] == "记一笔"
    assert value["hasForm"] is True
    assert int(value["fieldCount"]) >= 8
    assert "CNY" in str(value["currencyText"])
    assert float(value["submitWidth"]) > 80
    assert float(value["submitHeight"]) >= 32
    assert value["horizontalOverflow"] is False
