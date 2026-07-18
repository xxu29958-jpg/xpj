"""Product-shell contracts for the greenfield Web UI/IA rebuild."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.version import STATIC_ASSET_VERSION


@pytest.mark.parametrize(
    ("path", "domain", "heading"),
    [
        ("/web/pending?ledger_id=owner", "inbox", "待我处理"),
        ("/web/confirmed?ledger_id=owner", "transactions", "全部流水"),
        ("/web/debts?ledger_id=owner", "obligations", "我欠"),
        ("/web/budgets?ledger_id=owner", "plans", "预算"),
        ("/web/overview?ledger_id=owner", "insights", "本月概览"),
    ],
)
def test_primary_domains_render_new_modular_product_shell(
    web_client: TestClient,
    path: str,
    domain: str,
    heading: str,
) -> None:
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert f'data-domain="{domain}"' in body
    assert f'data-page="{domain}" data-page-level="primary"' in body
    assert re.search(rf"<h1[^>]*>\s*{re.escape(heading)}\s*</h1>", body)
    assert (
        f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    )
    assert (
        f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    )
    assert (
        f"/static/web/product/domains/{domain}.css?v={STATIC_ASSET_VERSION}"
        in body
    )

    # A rebuilt page owns its presentation module; the retired global stack
    # cannot silently leak back in.
    for retired in (
        "/static/web/web.css",
        "/static/web/_base.css",
        "/static/web/_shell.css",
        "/static/web/_misc.css",
        "/static/web/pages/product-system.css",
        "/static/web/pages/dashboard.css",
        "/static/web/pages/pending.css",
    ):
        assert retired not in body

    assert 'style="' not in body
    assert "<style" not in body


def test_product_shell_owns_month_picker_styles(web_client: TestClient) -> None:
    response = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    assert '<div class="month-picker">' in response.text
    assert "/static/web/product/shell.css" in response.text
    assert "/static/web/_shell.css" not in response.text

    css = web_client.get("/static/web/product/shell.css")
    assert css.status_code == 200
    assert re.search(r"\.month-picker\s*\{", css.text)
    assert re.search(r"\.month-picker a\s*\{", css.text)
    assert re.search(r"\.month-picker \.label\s*\{", css.text)
    assert "font-family: var(--font-numeric)" in css.text
    assert "width: var(--space-9)" in css.text
    assert "height: var(--space-9)" in css.text


def test_product_shell_keeps_appearance_secondary_to_ledger_context(
    web_client: TestClient,
) -> None:
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert 'id="theme-toggle"' not in body
    assert 'class="ledger-appearance"' in body
    assert 'data-theme-sync="local"' in body
    assert "data-theme-sync-status" in body
    assert 'aria-live="polite"' in body
    for theme in ("paper", "mono", "midnight"):
        assert f'data-theme-choice="{theme}"' in body

    theme_script = web_client.get("/static/web/desktop/theme.js")
    assert theme_script.status_code == 200
    assert "response.ok" in theme_script.text
    assert "主题已在此设备生效，但未能同步到其他设备。请稍后重试。" in theme_script.text


@pytest.mark.parametrize(
    ("path", "contracts"),
    [
        (
            "/web/pending?ledger_id=owner",
            (
                'class="product-page-header task-header"',
                'aria-label="待处理队列控制"',
                'class="inbox-summary"',
                'class="product-segments inbox-filters"',
            ),
        ),
        (
            "/web/confirmed?ledger_id=owner",
            (
                'class="product-page-header task-header ledger-workbench-header"',
                'aria-label="流水控制"',
                'class="ledger-secondary-insights"',
            ),
        ),
        (
            "/web/overview?ledger_id=owner",
            (
                'class="product-page-header task-header"',
                'class="insight-sequence"',
                'aria-label="本月任务与事实"',
            ),
        ),
        (
            "/web/library?ledger_id=owner",
            (
                'class="product-page-header task-header"',
                'class="library-directory library-management-list"',
                'aria-label="资料库管理"',
            ),
        ),
    ],
)
def test_priority_surfaces_expose_auditable_task_structure(
    web_client: TestClient,
    path: str,
    contracts: tuple[str, ...],
) -> None:
    response = web_client.get(path)

    assert response.status_code == 200
    for contract in contracts:
        assert contract in response.text


def test_primary_mutations_keep_real_csrf_and_occ_contracts(
    web_client: TestClient,
    identity,
) -> None:
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert pending.status_code == 200
    assert 'action="/web/review/bulk"' in pending.text
    assert re.search(
        r'name="csrf_token" value="[^"]+"',
        pending.text,
    )

    budgets = web_client.get("/web/budgets?ledger_id=owner")
    assert budgets.status_code == 200
    assert 'action="/web/budgets/save"' in budgets.text
    assert re.search(
        r'action="/web/budgets/save".*?name="csrf_token" value="[^"]+"',
        budgets.text,
        re.S,
    )

    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "产品壳测试",
            "category": "其他",
            "expense_time": "2026-07-18T08:00:00Z",
        },
    )
    assert created.status_code == 200
    expense_id = created.json()["id"]
    detail = web_client.get(
        f"/web/expenses/{expense_id}/edit"
        "?ledger_id=owner&return_to=confirmed"
    )

    assert detail.status_code == 200
    assert 'data-page="expense-detail" data-page-level="tertiary"' in detail.text
    assert "/static/web/product/detail.css" in detail.text
    assert re.search(
        r'action="/web/expenses/\d+/save".*?'
        r'name="csrf_token" value="[^"]+".*?'
        r'name="expected_row_version" value="[^"]+"',
        detail.text,
        re.S,
    )


def test_inbox_empty_state_matches_real_ingestion_routing(
    web_client: TestClient,
) -> None:
    pending = web_client.get("/web/pending?ledger_id=owner")

    assert pending.status_code == 200
    assert "新上传的截图、OCR 识别结果和导入草稿会出现在这里" in pending.text
    assert "手动记账可直接在流水中查看" in pending.text
    assert "手动记录和导入草稿会出现在这里" not in pending.text


def test_secondary_product_routes_follow_canonical_ownership(
    web_client: TestClient,
) -> None:
    repayment = web_client.get("/web/repayment-drafts?ledger_id=owner")
    assert repayment.status_code == 200
    assert 'data-domain="obligations"' in repayment.text
    assert 'data-page="obligations" data-page-level="secondary"' in repayment.text
    assert "往来 / 还款待确认" in repayment.text

    library = web_client.get("/web/library?ledger_id=owner")
    assert library.status_code == 200
    assert 'data-domain="transactions"' in library.text
    assert 'data-page="transactions" data-page-level="secondary"' in library.text
    for route in ("categories", "merchants", "tags", "rules", "recycle-bin"):
        assert f'href="/web/{route}?ledger_id=owner"' in library.text

    recycle_bin = web_client.get("/web/recycle-bin?ledger_id=owner")
    assert recycle_bin.status_code == 200
    assert 'data-domain="transactions"' in recycle_bin.text
    assert (
        'data-page="library-detail" data-page-level="tertiary"'
        in recycle_bin.text
    )
    assert "流水 / 资料库 / 回收站" in recycle_bin.text
    assert 'href="/web/library?ledger_id=owner"' in recycle_bin.text
    assert "数据与隐私" not in recycle_bin.text
    assert "dt-card" not in recycle_bin.text
    assert 'class="dt-' not in recycle_bin.text
    assert 'style="' not in recycle_bin.text


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/web/duplicates?ledger_id=owner", "疑似重复"),
        ("/web/search?ledger_id=owner", "搜索"),
        ("/web/categories?ledger_id=owner", "分类"),
        ("/web/merchants?ledger_id=owner", "商家"),
        ("/web/tags?ledger_id=owner", "标签"),
        ("/web/rules?ledger_id=owner", "规则"),
        ("/web/recycle-bin?ledger_id=owner", "回收站"),
        ("/web/repayment-drafts?ledger_id=owner", "还款待确认"),
    ],
)
def test_high_risk_task_pages_have_no_legacy_presentation_dom(
    web_client: TestClient,
    path: str,
    heading: str,
) -> None:
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert re.search(rf"<h1[^>]*>\s*{re.escape(heading)}\s*</h1>", body)
    assert 'class="dt-' not in body
    assert "dt-card" not in body
    assert 'style="' not in body
    assert "<style" not in body

    for form in re.findall(r'<form method="post".*?</form>', body, re.S):
        assert 'name="csrf_token"' in form


def test_product_css_modules_are_token_driven(web_client: TestClient) -> None:
    paths = [
        "/static/web/product/shell.css",
        "/static/web/product/components.css",
        "/static/web/product/detail.css",
        "/static/web/product/domains/inbox.css",
        "/static/web/product/domains/transactions.css",
        "/static/web/product/domains/obligations.css",
        "/static/web/product/domains/plans.css",
        "/static/web/product/domains/insights.css",
    ]

    for path in paths:
        response = web_client.get(path)
        assert response.status_code == 200, path
        css = response.text
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), path
        assert not re.search(r"\brgba?\(", css), path
