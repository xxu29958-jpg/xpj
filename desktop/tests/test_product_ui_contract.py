"""Executable product/data-plane contracts for the Desktop business window."""

from __future__ import annotations

import re
from pathlib import Path

_DESKTOP = Path(__file__).parents[1]
_PRODUCT_HTML = _DESKTOP / "backend_manager" / "product.html"
_PRODUCT_CSS = _DESKTOP / "backend_manager" / "product.css"
_PRODUCT_JS = _DESKTOP / "backend_manager" / "product.js"


def _html() -> str:
    return _PRODUCT_HTML.read_text(encoding="utf-8")


def _css() -> str:
    return _PRODUCT_CSS.read_text(encoding="utf-8")


def _js() -> str:
    return _PRODUCT_JS.read_text(encoding="utf-8")


def test_product_shell_exposes_exactly_five_business_domains() -> None:
    html = _html()
    js = _js()

    expected = (
        ("收件", "inbox", "1"),
        ("流水", "transactions", "2"),
        ("往来", "obligations", "3"),
        ("计划", "plans", "4"),
        ("洞察", "insights", "5"),
    )
    for label, workspace, shortcut in expected:
        assert f'data-workspace="{workspace}" data-shortcut="{shortcut}"' in html
        assert f'<span class="nav-title">{label}</span>' in html

    assert html.count('class="nav-item workspace-control') == len(expected)
    assert "Alt 1–5" in html
    assert 'event.key === "0"' in js
    assert "workbench" not in html + js
    assert "library" not in html + js


def test_product_shell_is_an_in_window_data_gui_not_a_web_launcher() -> None:
    html = _html()
    css = _css()
    js = _js()

    assert "min-height: 100dvh" in css
    assert 'class="data-stage"' in html
    assert 'class="data-table"' in html
    assert 'id="rowTableBody"' in html
    assert 'id="planView"' in html
    assert 'id="planGroups"' in html
    assert 'id="insightView"' in html
    assert 'id="insightFact"' in html
    assert 'class="inspector"' in html
    assert 'id="fieldList"' in html
    assert 'id="ledgerSelect"' in html
    assert 'id="refreshButton"' in html
    assert "window.open" not in js
    assert "/web" not in html + js
    assert "<iframe" not in html
    assert "window.location.assign" not in js


def test_product_shell_consumes_the_bounded_backend_projection_without_seed_rows() -> None:
    js = _js()

    assert '`/api/product/${requestedWorkspace}${query ? `?${query}` : ""}`' in js
    assert '{"X-Control-Token": window.CONTROL_TOKEN}' in js
    assert "payload.rows" in js
    assert "payload.ledgers" in js
    assert "state.payload?.total_count" in js
    assert "state.payload?.truncated" in js
    assert "row.amount_minor" in js
    assert "row.currency_code" in js
    assert "row.occurred_precision" in js
    assert "row.fields" in js
    assert "当前没有需要显示的记录。" in js
    assert "sampleRows" not in js
    assert "mockData" not in js
    assert "￥" not in js
    assert "¥" not in js


def test_table_and_inspector_have_keyboard_and_same_window_refresh_contracts() -> None:
    html = _html()
    css = _css()
    js = _js()

    assert 'event.key === "ArrowUp"' in js
    assert 'event.key === "ArrowDown"' in js
    assert 'event.key === "Home"' in js
    assert 'event.key === "End"' in js
    assert 'event.key === "F5"' in js
    assert 'event.key.toLowerCase() === "r"' in js
    assert "event.preventDefault();" in js
    assert "loadWorkspace({preserveSelection: true})" in js
    assert 'event.key === "/"' in js
    assert "selectRow(state.visibleRows[nextIndex].key" in js
    assert "window.history.replaceState" in js
    assert 'id="inspectorCloseButton"' in html
    assert 'aria-label="关闭当前行详情"' in html
    assert 'setAttribute("aria-haspopup", "dialog")' in js
    assert 'aria-keyshortcuts", "Enter"' in js
    assert 'window.matchMedia("(max-width: 1007px)")' in js
    assert 'event.key === "Enter"' in js
    assert 'event.key === "Escape"' in js
    assert "trapInspectorFocus(event)" in js
    assert "rowNode.focus();" in js
    assert "@media (max-width: 1007px)" in css
    assert "grid-template-columns: var(--rail-width) minmax(0, 1fr);" in css
    assert '.inspector:not([data-open="true"])' in css


def test_inbox_edit_confirm_and_ignore_use_real_occ_idempotent_command_bridge() -> None:
    html = _html()
    js = _js()

    assert 'id="inboxCommand"' in html
    assert 'id="commandAmount"' in html
    assert 'id="commandAmountLabel"' in html
    assert 'id="commandMerchant"' in html
    assert 'id="commandCategory"' in html
    assert 'data-action="save"' in html
    assert 'data-action="confirm"' in html
    assert 'data-action="ignore"' in html
    assert "row.edit.expected_row_version" in js
    assert "amountMinor !== row.edit.original_amount_minor" in js
    assert "BigInt(whole)" in js
    assert "absoluteMinor / divisor" in js
    assert "String(fraction).padStart" in js
    assert "exchange_rate_to_home: row.edit.exchange_rate_to_home" in js
    assert 'action === "save" && Object.keys(editFields).length === 0' in js
    assert "Math.round(Number(amount)" not in js
    assert "amount_cents: amountMinor" not in js
    assert '"expected_row_version"' not in js
    assert '"Idempotency-Key": state.pendingCommand.key' in js
    assert '"Content-Type": "application/json"' in js
    assert ('`/api/product/inbox/expenses/${encodeURIComponent(publicId)}/commands${query ? `?${query}` : ""}`') in js
    assert 'runInboxCommand("save")' in js
    assert 'runInboxCommand("confirm")' in js
    assert 'runInboxCommand("ignore")' in js
    assert 'id="confirmDialog"' in html
    assert "requestConfirmation({" in js
    assert 'title: "忽略这条收件？"' in js
    assert 'title: "解除这台电脑的账本绑定？"' in js
    assert 'payload.error === "state_conflict"' in js
    assert 'error === "permission_denied"' in js
    assert 'payload.error === "idempotency_key_in_progress"' in js
    assert "只读数据消费骨架" not in html + js
    assert "只读消费后端权威数据" not in html + js


def test_runtime_failure_fails_closed_and_recovery_stays_in_manager_plane() -> None:
    html = _html()
    js = _js()

    assert 'id="statusPanel"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-atomic="true"' in html
    assert 'aria-live="assertive"' not in html
    assert 'fetch("/api/status", {headers: requestHeaders()})' in js
    assert "status.product_available" in js
    assert "日常业务入口保持关闭，不会显示过期或伪造状态。" in js
    assert 'id="statusAction"' in html
    assert ">打开系统管理</a>" in html
    assert '$("statusAction").href = managerPath();' in js
    assert "{managerAction: true}" in js
    assert 'fetch("/api/start"' not in js
    assert 'fetch("/api/restart"' not in js
    assert "系统管理与备份" in html


def test_product_shell_keeps_supporting_copy_at_a_readable_desktop_scale() -> None:
    css = _css()
    pixel_sizes = [
        float(value)
        for value in re.findall(
            r"--primitive-font-size-[\w-]+:\s*(\d+(?:\.\d+)?)px",
            css,
        )
    ]

    assert pixel_sizes
    assert min(pixel_sizes) >= 12
    assert "--inspector-width: 304px" in css
    assert "@media (max-width: 1007px)" in css
    assert "small <= 640px, medium 641px-1007px, large >= 1008px" in css


def test_product_shell_uses_domain_specific_center_views_and_copy() -> None:
    html = _html()
    js = _js()

    assert "tableWorkspaceColumns" in js
    for label in (
        "待整理商家",
        "待确认金额",
        "入账商家",
        "已入账金额",
        "收到 / 消费时间",
        "入账状态",
        "待清算",
        "本月预算",
        "支出目标",
        "收入安排",
        "固定支出",
        "需要处理",
        "数据质量",
    ):
        assert label in html + js
    assert "renderPlanGroups" in js
    assert "renderInsights" in js
    assert "月度趋势" not in html + js
    assert "趋势与提醒" not in html + js


def test_product_shell_preserves_trusted_rows_while_refreshing() -> None:
    js = _js()
    load_workspace = js[js.index("async function loadWorkspace") : js.index("function switchWorkspace")]
    switch_workspace = js[js.index("function switchWorkspace") : js.index("async function refreshProductPrincipal")]

    assert "clearProductData" not in load_workspace
    assert 'setAttribute("aria-busy", "true")' in load_workspace
    assert 'setAttribute("aria-busy", "false")' in load_workspace
    assert 'const requestedSelection = preserveSelection ? state.selectedKey : "";' in load_workspace
    assert "const preferredKey = preserveSelection ? state.selectedKey : requestedSelection;" in load_workspace
    assert "const activeLedger = state.ledgerId;" in switch_workspace
    assert "state.ledgerId = activeLedger;" in switch_workspace


def test_product_shell_keeps_internal_occ_and_currency_semantics_out_of_copy() -> None:
    html = _html()
    js = _js()

    assert "并发版本" not in html + js
    assert "金额（元）" not in html + js
    assert "minor_unit_digits" in js
    assert "editableCurrencyLabel" in js
    assert 'precision === "date"' in js


def test_product_assets_are_modular_and_keep_app_token_out_of_javascript() -> None:
    html = _html()
    css = _css()
    js = _js()

    assert "<style" not in html
    assert "style=" not in html
    assert '<link rel="stylesheet" href="/product.css">' in html
    assert '<script src="/product.js" defer></script>' in html
    assert html.count("<script") == 1
    assert "__CONTROL_TOKEN__" in html
    assert "__CONTROL_TOKEN__" not in css + js
    assert 'meta[name="ticketbox-control-token"]' in js
    assert "controlTokenMeta?.remove()" in js
    assert "clearProductData" in js
    assert 'fetch("/api/product/session"' not in html
    assert '"/api/product/session"' in js
    assert '"/api/product/ledger/switch"' in js
    assert "switchProductLedger" in js


def test_product_css_uses_three_token_layers_without_component_literals() -> None:
    css = _css()
    component_rules = css[css.index("* {") :]
    component_rules_without_comments = re.sub(
        r"/\*.*?\*/",
        "",
        component_rules,
        flags=re.DOTALL,
    )
    component_rules_without_breakpoint = component_rules_without_comments
    for breakpoint in ("1007px", "640px"):
        component_rules_without_breakpoint = component_rules_without_breakpoint.replace(
            f"@media (max-width: {breakpoint})",
            "@media (max-width: BREAKPOINT)",
        )

    assert "Primitive tokens: palette, spacing, type and shape." in css
    assert "Local mirror of the product-wide semantic vocabulary." in css
    assert "Semantic tokens: surfaces, text, borders, state and focus." in css
    assert "Component and layout tokens: titlebar, rail, inspector, rows and controls." in css
    for token in (
        "--titlebar-height",
        "--rail-width",
        "--inspector-width",
        "--row-height",
        "--control-height",
        "--surface-panel",
        "--text-primary",
        "--border-default",
        "--focus-ring",
    ):
        assert token in css
    assert not re.search(
        r"#[0-9a-fA-F]{3,8}|rgba?\(",
        component_rules,
    )
    raw_pixels = re.findall(
        r"(?<![\w-])-?\d+(?:\.\d+)?px",
        component_rules_without_breakpoint,
    )
    assert set(raw_pixels) <= {"1px"}
    assert "border: 1px" not in component_rules
    assert ".visually-hidden" in css
    assert "var(--primitive-line-height-relaxed)5" not in css
    assert "line-height: var(--primitive-line-height-relaxed);" in css


def test_compact_navigation_keeps_meaningful_accessible_names() -> None:
    html = _html()

    for label in ("收件", "流水", "往来", "计划", "洞察"):
        assert f'aria-label="{label}"' in html


def test_manager_and_product_window_remain_distinct_jobs_and_both_ship() -> None:
    product_html = _html()
    manager_html = (_DESKTOP / "backend_manager" / "ui.html").read_text(encoding="utf-8")
    spec = (_DESKTOP / "packaging" / "ticketbox-manager.spec").read_text(encoding="utf-8")

    assert 'aria-label="小票夹桌面一级导航"' in product_html
    assert "系统管理与备份" in product_html
    assert "返回日常账务" in manager_html
    assert "小票夹管理器" in manager_html
    assert '"product.html"' in spec
    assert '"product.css"' in spec
    assert '"product.js"' in spec
