"""Real Edge consumer checks for the Manager's compact and desktop layouts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from backend_manager import desktop_shell
from backend_manager.desktop_shell import discover_edge_executable
from backend_manager.manager_startup import ManagerWindowSession
from tests import _edge_cdp
from tests._edge_cdp import evaluate_page, wait_for_app_window_close

_UI_HTML = Path(__file__).resolve().parents[1] / "backend_manager" / "ui.html"
_PRODUCT_HTML = Path(__file__).resolve().parents[1] / "backend_manager" / "product.html"
_PRODUCT_CSS = Path(__file__).resolve().parents[1] / "backend_manager" / "product.css"
_PRODUCT_JS = Path(__file__).resolve().parents[1] / "backend_manager" / "product.js"
_STARTUP_SCRIPT = "    refresh();\n    setInterval(refresh, 2500);"
_PRODUCT_STARTUP_SCRIPT = "refresh();\nsetInterval(refresh, 5000);"


def _write_product_fixture(
    tmp_path: Path,
    *,
    page_name: str,
    startup_script: str,
) -> Path:
    html = _PRODUCT_HTML.read_text(encoding="utf-8")
    javascript = _PRODUCT_JS.read_text(encoding="utf-8")
    assert javascript.count(_PRODUCT_STARTUP_SCRIPT) == 1
    html = html.replace('href="/product.css"', 'href="product.css"')
    html = html.replace('src="/product.js"', 'src="product.js"')
    (tmp_path / "product.css").write_text(
        _PRODUCT_CSS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "product.js").write_text(
        javascript.replace(_PRODUCT_STARTUP_SCRIPT, startup_script),
        encoding="utf-8",
    )
    page = tmp_path / page_name
    page.write_text(html, encoding="utf-8")
    return page


def _status(*, degraded: bool) -> dict[str, object]:
    return {
        "runtime_mode": "installed",
        "running": not degraded,
        "health": not degraded,
        "health_state": "pending" if degraded else "healthy",
        "health_detail": "无法读取 Ticketbox 运行状态。" if degraded else "安装身份已验证。",
        "uptime_seconds": 42,
        "pid": 1234,
        "port": 8000,
        "auto_restart": True,
        "auto_restart_configurable": False,
        "restarts": 0,
        "backend_service_state": "unknown" if degraded else "running",
        "database_service_state": "unknown" if degraded else "running",
        "lan": "仅本机监听",
        "tunnel": None,
        "public_endpoint_state": "local_only" if not degraded else "unknown",
        "mobile_endpoint_state": "local_only" if not degraded else "unknown",
        "android_binding_state": "setup_required" if not degraded else "unknown",
        "iphone_upload_state": "setup_required" if not degraded else "unknown",
        "runtime_access_state": "available" if not degraded else "unknown",
        "owner_state": "configured" if not degraded else "unknown",
        "owner_recovery_channel": "managed_host" if not degraded else "unknown",
        "owner_url": None if degraded else "http://127.0.0.1:8000/owner",
        "product_url": None if degraded else "http://127.0.0.1:8000/web",
        "product_available": not degraded,
        "version": "1.2.0",
        "service_controls_available": not degraded,
        "log": ["运行投影不可用；未使用启动时的旧安装信息。"] if degraded else ["服务正常。"],
        "control_error": "安装信息已变化或不可用；请修复或重新安装小票夹。" if degraded else None,
        "action_notice": None,
        "diagnostic_bundle_file": None,
        "manager_shutdown_requested": False,
    }


def _product_payload(workspace: str) -> dict[str, object]:
    titles = {
        "inbox": ("收件", "早餐店", "待补商家"),
        "transactions": ("流水", "地铁", "书店"),
        "obligations": ("往来", "家庭垫付", "信用卡"),
        "plans": ("计划", "本月预算", "工资"),
        "insights": ("洞察", "月度概览", "疑似重复"),
    }
    kinds = {
        "inbox": ("expense", "expense"),
        "transactions": ("expense", "expense"),
        "obligations": ("debt", "debt"),
        "plans": ("budget", "income"),
        "insights": ("report_summary", "quality_metric"),
    }
    title, first, second = titles[workspace]
    first_kind, second_kind = kinds[workspace]
    inbox = workspace == "inbox"
    second_occurred_at = "2026-07-21" if workspace == "plans" else "2026-07-18T06:30:00Z"
    second_occurred_precision = "date" if workspace == "plans" else "instant"
    return {
        "workspace": workspace,
        "title": title,
        "ledger_id": "owner",
        "ledger_name": "我的小票夹",
        "role": "owner",
        "generated_at": "2026-07-18T08:00:00Z",
        "rows": [
            {
                "key": "expense:fixture-inbox-first" if inbox else f"{workspace}:first",
                "kind": first_kind,
                "title": first,
                "subtitle": "最近整理",
                "status": "active",
                "status_label": "生效中",
                "amount_minor": 1880,
                "currency_code": "CNY",
                "value_text": None,
                "occurred_at": "2026-07-18T07:30:00Z",
                "occurred_precision": "instant",
                "fields": [{"label": "来源", "value": "手机导入"}],
                "capabilities": ["save", "confirm", "ignore"] if inbox else [],
                "edit": {
                    "expected_row_version": 1,
                    "amount_minor": 1880,
                    "currency_code": "CNY",
                    "currency_symbol": "¥",
                    "minor_unit_digits": 2,
                    "home_amount_minor": 1880,
                    "home_currency_code": "CNY",
                    "original_amount_minor": 1880,
                    "original_currency_code": "CNY",
                    "exchange_rate_to_home": None,
                    "exchange_rate_date": None,
                    "exchange_rate_source": "base",
                    "fx_status": "ready",
                    "merchant": first,
                    "category": "餐饮",
                }
                if inbox
                else None,
            },
            {
                "key": "expense:fixture-inbox-second" if inbox else f"{workspace}:second",
                "kind": second_kind,
                "title": second,
                "subtitle": "第二行用于键盘选择",
                "status": "attention",
                "status_label": "需留意",
                "amount_minor": None,
                "currency_code": None,
                "value_text": "2 项",
                "occurred_at": second_occurred_at,
                "occurred_precision": second_occurred_precision,
                "fields": [{"label": "状态", "value": "等待人工判断"}],
                "capabilities": ["save", "confirm", "ignore"] if inbox else [],
                "edit": {
                    "expected_row_version": 2,
                    "amount_minor": None,
                    "currency_code": "CNY",
                    "currency_symbol": "¥",
                    "minor_unit_digits": 2,
                    "home_amount_minor": None,
                    "home_currency_code": "CNY",
                    "original_amount_minor": None,
                    "original_currency_code": "CNY",
                    "exchange_rate_to_home": None,
                    "exchange_rate_date": None,
                    "exchange_rate_source": "base",
                    "fx_status": "ready",
                    "merchant": second,
                    "category": "其他",
                }
                if inbox
                else None,
            },
        ],
        "total_count": 2,
        "truncated": False,
        "empty_title": "当前没有数据",
        "empty_detail": "不会生成示例记录。",
        "ledgers": [
            {
                "ledger_id": "owner",
                "name": "我的小票夹",
                "role": "owner",
                "is_default": True,
                "is_current": True,
            },
            {
                "ledger_id": "family",
                "name": "家庭账本",
                "role": "viewer",
                "is_default": False,
                "is_current": False,
            },
        ],
    }


def _probe_script(status: dict[str, object]) -> str:
    return f"""    render({json.dumps(status, ensure_ascii=False)});
    const visibleButtons = [...document.querySelectorAll("button")].filter((button) => {{
      const style = getComputedStyle(button);
      const rect = button.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    }});
    const overlaps = [];
    for (let left = 0; left < visibleButtons.length; left += 1) {{
      const a = visibleButtons[left].getBoundingClientRect();
      for (let right = left + 1; right < visibleButtons.length; right += 1) {{
        const b = visibleButtons[right].getBoundingClientRect();
        if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) {{
          overlaps.push([visibleButtons[left].id, visibleButtons[right].id]);
        }}
      }}
    }}
    const result = {{
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      overlaps,
      unnamedButtons: visibleButtons.filter((button) =>
        !(button.getAttribute("aria-label") || button.textContent.trim())
      ).length,
      clippedButtons: visibleButtons.filter((button) =>
        button.scrollWidth > button.clientWidth + 1 || button.scrollHeight > button.clientHeight + 1
      ).length,
      primaryDisabled: document.getElementById("primaryAction").disabled,
      primaryAction: document.getElementById("primaryAction").dataset.action,
      primaryText: document.getElementById("primaryAction").textContent.trim(),
      diagnosticsDisabled: document.getElementById("diagnosticExportAction").disabled,
      overallText: document.getElementById("overallText").textContent,
      runtimeText: document.getElementById("runtimeLabel").textContent,
      serviceTitle: document.getElementById("serviceTitle").textContent
    }};
    document.body.setAttribute("data-layout-probe", JSON.stringify(result));"""


def _render_with_edge(tmp_path: Path, *, width: int, height: int, degraded: bool) -> dict[str, object]:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Windows Desktop Manager layout gate"
    source = _UI_HTML.read_text(encoding="utf-8")
    assert source.count(_STARTUP_SCRIPT) == 1
    rendered = source.replace(_STARTUP_SCRIPT, _probe_script(_status(degraded=degraded)))
    page = tmp_path / f"manager-{width}x{height}-{'degraded' if degraded else 'healthy'}.html"
    page.write_text(rendered, encoding="utf-8")
    profile = tmp_path / f"edge-profile-{width}-{height}-{degraded}"
    value = evaluate_page(
        edge,
        profile=profile,
        url=page.as_uri(),
        width=width,
        height=height,
        expression="document.body && document.body.getAttribute('data-layout-probe') || undefined",
    )
    assert isinstance(value, str)
    return json.loads(value)


def _render_behavior_probe(tmp_path: Path) -> dict[str, object]:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Windows Desktop Manager behavior gate"
    source = _UI_HTML.read_text(encoding="utf-8")
    assert source.count(_STARTUP_SCRIPT) == 1
    healthy = _status(degraded=False)
    stopped = {**healthy, "running": False, "health": False, "backend_service_state": "stopped"}
    script = f"""    (async () => {{
      const healthy = {json.dumps(healthy, ensure_ascii=False)};
      const stopped = {json.dumps(stopped, ensure_ascii=False)};
      render(healthy);
      window.fetch = async () => {{ throw new Error("offline"); }};
      let offlineThrew = false;
      try {{ await refresh(); }} catch (_error) {{ offlineThrew = true; }}
      const offline = {{
        threw: offlineThrew,
        primaryDisabled: document.getElementById("primaryAction").disabled,
        androidDisabled: document.getElementById("androidAction").disabled,
        overallText: document.getElementById("overallText").textContent
      }};

      render(healthy);
      window.fetch = async (url) => {{
        if (url === "/api/stop") {{
          return {{status: 200, ok: true, json: async () => stopped}};
        }}
        throw new Error("offline");
      }};
      await act("stop", document.getElementById("primaryAction"));
      const primary = document.getElementById("primaryAction");
      document.body.setAttribute("data-behavior-probe", JSON.stringify({{
        offline,
        primaryAction: primary.dataset.action,
        primaryText: primary.textContent.trim()
      }}));
    }})();"""
    page = tmp_path / "manager-behavior.html"
    page.write_text(source.replace(_STARTUP_SCRIPT, script), encoding="utf-8")
    value = evaluate_page(
        edge,
        profile=tmp_path / "edge-profile-behavior",
        url=page.as_uri(),
        width=820,
        height=660,
        expression="document.body && document.body.getAttribute('data-behavior-probe') || undefined",
    )
    assert isinstance(value, str)
    return json.loads(value)


def _render_product_with_edge(tmp_path: Path, *, width: int, height: int) -> dict[str, object]:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Windows Desktop product layout gate"
    payloads = {
        workspace: _product_payload(workspace)
        for workspace in ("inbox", "transactions", "obligations", "plans", "insights")
    }
    script = f"""    (async () => {{
      const payloads = {json.dumps(payloads, ensure_ascii=False)};
      const fetchCalls = [];
      const commandCalls = [];
      const switchCalls = [];
      let activeLedger = "owner";
      let windowOpenCalls = 0;
      let deferNextWorkspaceResponse = false;
      let releaseWorkspaceResponse = null;
      window.open = () => {{ windowOpenCalls += 1; throw new Error("window.open forbidden"); }};
      window.fetch = async (url, options = {{}}) => {{
        const value = String(url);
        fetchCalls.push(value);
        if (value === "/api/status") {{
          return {{ok: true, json: async () => ({json.dumps(_status(degraded=False), ensure_ascii=False)})}};
        }}
        if (value === "/api/product/session") {{
          return {{
            ok: true,
            status: 200,
            json: async () => ({{
              configured: true,
              account_name: "我",
              ledger_id: "owner",
              ledger_name: "我的小票夹",
              device_name: "小票夹 Desktop",
              role: "owner",
              expires_at: null
            }})
          }};
        }}
        if (value.startsWith("/api/product/inbox/expenses/") && options.method === "POST") {{
          commandCalls.push({{
            url: value,
            method: options.method,
            idempotencyKey: options.headers["Idempotency-Key"],
            controlToken: options.headers["X-Control-Token"],
            payload: JSON.parse(options.body)
          }});
          return {{
            ok: true,
            status: 200,
            json: async () => ({{
              action: "confirm",
              message: "收件已确认并进入流水。",
              expense_status: "confirmed",
              row_version: 2
            }})
          }};
        }}
        if (value === "/api/product/ledger/switch" && options.method === "POST") {{
          const payload = JSON.parse(options.body);
          switchCalls.push({{
            ledgerId: payload.ledger_id,
            controlToken: options.headers["X-Control-Token"]
          }});
          activeLedger = payload.ledger_id;
          return {{
            ok: true,
            status: 200,
            json: async () => ({{
              configured: true,
              account_name: "我",
              ledger_id: activeLedger,
              ledger_name: "家庭账本",
              device_name: "小票夹 Desktop",
              role: "viewer",
              expires_at: null
            }})
          }};
        }}
        const match = value.match(/^\\/api\\/product\\/([^?]+)/);
        const workspace = match ? match[1] : "";
        const workspacePayload = payloads[workspace]
          ? structuredClone(payloads[workspace])
          : null;
        if (workspacePayload) {{
          workspacePayload.ledger_id = activeLedger;
          workspacePayload.ledger_name = activeLedger === "family" ? "家庭账本" : "我的小票夹";
          workspacePayload.role = activeLedger === "family" ? "viewer" : "owner";
          workspacePayload.ledgers.forEach((ledger) => {{
            ledger.is_current = ledger.ledger_id === activeLedger;
          }});
        }}
        const response = {{
          ok: Boolean(workspacePayload),
          status: workspacePayload ? 200 : 404,
          json: async () => workspacePayload || {{message: "missing"}}
        }};
        if (workspacePayload && deferNextWorkspaceResponse) {{
          deferNextWorkspaceResponse = false;
          return await new Promise((resolve) => {{
            releaseWorkspaceResponse = () => resolve(response);
          }});
        }}
        return response;
      }};
      const shellPath = window.location.pathname;
      await refresh();
      await new Promise((resolve) => setTimeout(resolve, 10));
      const primaryRail = document.querySelector(".primary-rail");
      const dataStage = document.getElementById("dataStage");
      const inspector = document.getElementById("inspector");
      const inspectorCloseButton = document.getElementById("inspectorCloseButton");
      const firstRow = document.querySelector(".data-row");
      const inspectorDrawer = {{
        applicable: innerWidth <= 1007,
        railWidth: primaryRail.getBoundingClientRect().width,
        stageWidthClosed: dataStage.getBoundingClientRect().width,
        openedByClick: false,
        openWidth: 0,
        stageWidthWhileOpen: 0,
        role: "",
        modal: "",
        closeButtonFocused: false,
        closedByButton: false,
        focusRestoredAfterButton: false,
        openedByEnter: false,
        tabWrappedToClose: false,
        closedByEscape: false,
        focusRestoredAfterEscape: false
      }};
      if (inspectorDrawer.applicable && firstRow) {{
        firstRow.click();
        inspectorDrawer.openedByClick = inspector.dataset.open === "true";
        inspectorDrawer.openWidth = inspector.getBoundingClientRect().width;
        inspectorDrawer.stageWidthWhileOpen = dataStage.getBoundingClientRect().width;
        inspectorDrawer.role = inspector.getAttribute("role") || "";
        inspectorDrawer.modal = inspector.getAttribute("aria-modal") || "";
        inspectorDrawer.closeButtonFocused = document.activeElement === inspectorCloseButton;
        inspectorCloseButton.click();
        inspectorDrawer.closedByButton = inspector.dataset.open === "false";
        inspectorDrawer.focusRestoredAfterButton = document.activeElement === firstRow;

        firstRow.focus();
        document.dispatchEvent(new KeyboardEvent(
          "keydown",
          {{key: "Enter", bubbles: true, cancelable: true}}
        ));
        inspectorDrawer.openedByEnter = inspector.dataset.open === "true";
        const drawerFocusable = [...inspector.querySelectorAll(
          "button:not([hidden]):not([disabled]), input:not([hidden]):not([disabled]), " +
          "select:not([hidden]):not([disabled]), a[href]:not([hidden]), " +
          '[tabindex]:not([tabindex="-1"])'
        )].filter((element) => element.getClientRects().length > 0);
        drawerFocusable[drawerFocusable.length - 1].focus();
        document.dispatchEvent(new KeyboardEvent(
          "keydown",
          {{key: "Tab", bubbles: true, cancelable: true}}
        ));
        inspectorDrawer.tabWrappedToClose = document.activeElement === inspectorCloseButton;
        document.dispatchEvent(new KeyboardEvent(
          "keydown",
          {{key: "Escape", bubbles: true, cancelable: true}}
        ));
        inspectorDrawer.closedByEscape = inspector.dataset.open === "false";
        inspectorDrawer.focusRestoredAfterEscape = document.activeElement === firstRow;
      }}
      const inboxFormVisible = !document.getElementById("inboxCommand").hidden;
      const inboxCurrencyLabel = document.getElementById("commandAmountLabel").textContent;
      const inboxAmountValue = document.getElementById("commandAmount").value;
      const inboxHeaders = [...document.querySelectorAll(".data-table th")].map(
        (node) => node.textContent
      );
      document.getElementById("ignoreCommand").click();
      const ignoreConfirmationOpened = (
        document.getElementById("confirmDialog").open
        && document.getElementById("confirmTitle").textContent === "忽略这条收件？"
        && document.getElementById("confirmActionButton").textContent === "确认忽略"
      );
      document.getElementById("confirmCancelButton").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const ignoreCancellationPreventedCommand = commandCalls.length === 0;
      document.getElementById("confirmCommand").click();
      await new Promise((resolve) => setTimeout(resolve, 20));
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "2", altKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 10));
      const transactionHeaders = [...document.querySelectorAll(".data-table th")].map(
        (node) => node.textContent
      );
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "3", altKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 10));
      const obligationHeaders = [...document.querySelectorAll(".data-table th")].map(
        (node) => node.textContent
      );
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "4", altKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 10));
      const keyboardWorkspace = document.querySelector(".workspace-control.is-current").dataset.workspace;
      const keyboardWorkspaceTitle = document.getElementById("workspaceTitle").textContent;
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "ArrowDown"}}));
      const selectedTitle = document.getElementById("inspectorTitle").textContent;
      const planGroupCount = document.querySelectorAll(".plan-group").length;
      const planDateText = document.querySelector(
        '[data-key="plans:second"] .record-meta'
      ).textContent;
      const searchInput = document.getElementById("searchInput");
      searchInput.value = selectedTitle;
      searchInput.dispatchEvent(new Event("input"));
      const callsBeforeRefresh = fetchCalls.length;
      deferNextWorkspaceResponse = true;
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "r", ctrlKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 0));
      const refreshPreservedContext = (
        searchInput.value === selectedTitle
        && document.querySelectorAll(".data-row").length === 1
        && document.querySelector('.data-row[aria-selected="true"]').dataset.key === "plans:second"
        && document.getElementById("dataStage").getAttribute("aria-busy") === "true"
      );
      releaseWorkspaceResponse();
      await new Promise((resolve) => setTimeout(resolve, 10));
      const refreshRestoredContext = (
        searchInput.value === selectedTitle
        && document.querySelectorAll(".data-row").length === 1
        && document.querySelector('.data-row[aria-selected="true"]').dataset.key === "plans:second"
      );
      searchInput.value = "不存在的记录";
      searchInput.dispatchEvent(new Event("input"));
      const filterEmptyPanelVisible = !document.getElementById("emptyPanel").hidden;
      searchInput.focus();
      document.dispatchEvent(new KeyboardEvent(
        "keydown",
        {{key: "Escape", bubbles: true, cancelable: true}}
      ));
      const filterClearedFromEmptyState = (
        searchInput.value === ""
        && document.getElementById("emptyPanel").hidden
      );
      const ledgerSelect = document.getElementById("ledgerSelect");
      ledgerSelect.value = "family";
      ledgerSelect.dispatchEvent(new Event("change"));
      await new Promise((resolve) => setTimeout(resolve, 20));
      const callsBeforeLedgerWorkspaceSwitch = fetchCalls.length;
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "5", altKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 10));
      const ledgerPreservedAcrossWorkspace = (
        document.getElementById("ledgerSelect").value === "family"
        && fetchCalls.slice(callsBeforeLedgerWorkspaceSwitch).some(
          (call) => call.startsWith("/api/product/insights?ledger_id=family")
        )
      );
      const insightFactVisible = !document.getElementById("insightFact").hidden;
      const insightAttentionCount = document.querySelectorAll(
        "#attentionRecords .data-row"
      ).length;
      const insightQualityCount = document.querySelectorAll(
        "#qualityRecords .data-row"
      ).length;
      document.dispatchEvent(new KeyboardEvent("keydown", {{key: "4", altKey: true}}));
      await new Promise((resolve) => setTimeout(resolve, 10));
      const callsBeforeUnpairConfirmation = fetchCalls.length;
      document.getElementById("unpairButton").click();
      const unpairConfirmationOpened = (
        document.getElementById("confirmDialog").open
        && document.getElementById("confirmTitle").textContent === "解除这台电脑的账本绑定？"
        && document.getElementById("confirmActionButton").textContent === "解除绑定"
      );
      document.getElementById("confirmCancelButton").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      const unpairCancellationPreventedRequest = (
        fetchCalls.length === callsBeforeUnpairConfirmation
      );
      const visibleButtons = [...document.querySelectorAll("button")].filter((button) => {{
        const style = getComputedStyle(button);
        const rect = button.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      }});
      const supportingCopy = [...document.querySelectorAll(
        ".connection, .rail-label, .nav-index, .nav-title, .shortcut-note, .manage-link, " +
        ".workspace-kicker, .workspace-summary, .row-count, .sync-note, .data-table th, " +
        ".data-row td, .status-pill, .inspector-kicker, .inspector-subtitle, " +
        ".field-row dt, .field-row dd, .inspector-footer"
      )].filter((node) => getComputedStyle(node).display !== "none");
      const result = {{
        viewportWidth: innerWidth,
        windowsSizeClass: innerWidth <= 640 ? "small" : innerWidth <= 1007 ? "medium" : "large",
        compactShell: getComputedStyle(document.querySelector(".nav-title")).display === "none",
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        unnamedButtons: visibleButtons.filter((button) =>
          !(button.getAttribute("aria-label") || button.textContent.trim())
        ).length,
        clippedButtons: visibleButtons.filter((button) =>
          button.scrollWidth > button.clientWidth + 1 || button.scrollHeight > button.clientHeight + 1
        ).length,
        railFillsWorkspace: (
          document.querySelector(".primary-rail").getBoundingClientRect().height +
          document.querySelector(".titlebar").getBoundingClientRect().height
        ) >= innerHeight - 1,
        workspaceLabels: [...document.querySelectorAll(".nav-title")].map((node) => node.textContent.trim()),
        activeWorkspace: document.querySelector(".workspace-control.is-current").dataset.workspace,
        workspaceTitle: document.getElementById("workspaceTitle").textContent,
        keyboardWorkspace,
        keyboardWorkspaceTitle,
        rowCount: document.querySelectorAll(".data-row").length,
        selectedRows: document.querySelectorAll('.data-row[aria-selected="true"]').length,
        selectedTitle,
        inspectorFieldCount: document.querySelectorAll(".field-row").length,
        shellPathStable: window.location.pathname === shellPath,
        windowOpenCalls,
        fetchCalls,
        commandCalls,
        switchCalls,
        inboxFormVisible,
        inboxCurrencyLabel,
        inboxAmountValue,
        inboxHeaders,
        transactionHeaders,
        obligationHeaders,
        ignoreConfirmationOpened,
        ignoreCancellationPreventedCommand,
        planGroupCount,
        planDateText,
        refreshPreservedContext,
        refreshRestoredContext,
        filterEmptyPanelVisible,
        filterClearedFromEmptyState,
        insightFactVisible,
        insightAttentionCount,
        insightQualityCount,
        unpairConfirmationOpened,
        unpairCancellationPreventedRequest,
        keyboardRefreshAddedCall: fetchCalls.length > callsBeforeRefresh,
        connectionText: document.getElementById("connectionText").textContent,
        disabledWorkspaces: document.querySelectorAll(".workspace-control:disabled").length,
        ledgerOptionCount: document.getElementById("ledgerSelect").options.length,
        selectedLedger: document.getElementById("ledgerSelect").value,
        ledgerPreservedAcrossWorkspace,
        roleNote: document.getElementById("roleNote").textContent,
        workspaceContentWidth: [...document.querySelectorAll(
          "#tableView, #planView, #insightView"
        )].find((node) => !node.hidden).getBoundingClientRect().width,
        inspectorWidth: document.querySelector(".inspector").getBoundingClientRect().width,
        inspectorDrawer,
        minimumSupportingFontPx: Math.min(
          ...supportingCopy.map((node) => Number.parseFloat(getComputedStyle(node).fontSize))
        )
      }};
      document.body.setAttribute("data-product-layout-probe", JSON.stringify(result));
    }})();"""
    page = _write_product_fixture(
        tmp_path,
        page_name=f"product-{width}x{height}.html",
        startup_script=script,
    )
    value = evaluate_page(
        edge,
        profile=tmp_path / f"edge-product-profile-{width}-{height}",
        url=page.as_uri(),
        width=width,
        height=height,
        expression=("document.body && document.body.getAttribute('data-product-layout-probe') || undefined"),
    )
    assert isinstance(value, str)
    return json.loads(value)


def _render_product_fail_closed_probe(tmp_path: Path) -> dict[str, object]:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Desktop stale-data gate"
    payload = _product_payload("plans")
    script = f"""    (async () => {{
      const payload = {json.dumps(payload, ensure_ascii=False)};
      const capture = () => ({{
        payloadNull: state.payload === null,
        payloadWorkspace: state.payload?.workspace || "",
        payloadGeneratedAt: state.payload?.generated_at || "",
        rows: state.rows.length,
        rowKeys: state.rows.map((row) => row.key),
        visibleRows: state.visibleRows.length,
        visibleRowKeys: state.visibleRows.map((row) => row.key),
        selectedKey: state.selectedKey,
        ledgerId: state.ledgerId,
        pendingCommandNull: state.pendingCommand === null,
        pendingCommand: state.pendingCommand,
        domRows: document.querySelectorAll(".data-row").length,
        domTitles: [...document.querySelectorAll(".data-row .record-title")]
          .map((node) => node.textContent),
        inspectorTitle: document.getElementById("inspectorTitle").textContent,
        inspectorValue: document.getElementById("inspectorValue").textContent,
        inspectorFields: document.querySelectorAll("#fieldList .field-row").length,
        roleNote: document.getElementById("roleNote").textContent,
        commandAmount: document.getElementById("commandAmount").value,
        syncNote: document.getElementById("syncNote").textContent,
        connectionText: document.getElementById("connectionText").textContent,
        statusPanelHidden: document.getElementById("statusPanel").hidden,
        refreshDisabled: document.getElementById("refreshButton").disabled,
        ledgerOptions: [...document.getElementById("ledgerSelect").options]
          .map((option) => option.textContent)
      }});
      const seedHealthy = () => {{
        state.principalReady = true;
        setWorkspaceAvailability(true);
        renderPayload(structuredClone(payload), {{preferredKey: "plans:first"}});
        state.pendingCommand = {{signature: "sensitive-draft", key: "retry-key"}};
        document.getElementById("commandAmount").value = "999.99";
      }};

      state.principalReady = true;
      setWorkspaceAvailability(true);
      window.fetch = async () => ({{
        ok: true,
        status: 200,
        json: async () => structuredClone(payload)
      }});
      await loadWorkspace({{preserveSelection: true}});
      state.pendingCommand = {{signature: "sensitive-draft", key: "retry-key"}};
      document.getElementById("commandAmount").value = "999.99";
      const healthy = capture();

      window.fetch = async () => ({{
        ok: false,
        status: 503,
        json: async () => ({{
          error: "service_unavailable",
          message: "服务暂时不可用"
        }})
      }});
      await loadWorkspace({{preserveSelection: true}});
      const serviceUnavailable = capture();

      window.fetch = async () => {{ throw new Error("network offline"); }};
      await loadWorkspace({{preserveSelection: true}});
      const networkFailure = capture();

      window.fetch = async () => ({{
        ok: false,
        status: 401,
        json: async () => ({{
          error: "invalid_token",
          message: "桌面身份已失效"
        }})
      }});
      await loadWorkspace({{preserveSelection: true}});
      const unauthorized = capture();

      seedHealthy();
      window.fetch = async () => ({{
        ok: false,
        status: 403,
        json: async () => ({{
          error: "permission_denied",
          message: "当前身份无权访问"
        }})
      }});
      await loadWorkspace({{preserveSelection: true}});
      const forbidden = capture();

      seedHealthy();
      window.fetch = async () => new Promise(() => {{}});
      const ledger = document.getElementById("ledgerSelect");
      ledger.value = "family";
      ledger.dispatchEvent(new Event("change"));
      await Promise.resolve();
      const ledgerChange = capture();

      document.body.setAttribute(
        "data-product-fail-closed-probe",
        JSON.stringify({{
          healthy,
          serviceUnavailable,
          networkFailure,
          unauthorized,
          forbidden,
          ledgerChange
        }})
      );
    }})();"""
    page = _write_product_fixture(
        tmp_path,
        page_name="product-fail-closed.html",
        startup_script=script,
    )
    value = evaluate_page(
        edge,
        profile=tmp_path / "edge-product-fail-closed-profile",
        url=page.as_uri(),
        width=1180,
        height=760,
        expression=("document.body && document.body.getAttribute('data-product-fail-closed-probe') || undefined"),
    )
    assert isinstance(value, str)
    return json.loads(value)


def _render_stopped_product_with_edge(
    tmp_path: Path,
    *,
    width: int,
    height: int,
) -> dict[str, object]:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Windows Desktop recovery gate"
    healthy = _status(degraded=False)
    stopped = {
        **healthy,
        "running": False,
        "health": False,
        "health_state": "stopped",
        "health_detail": "",
        "backend_service_state": "stopped",
        "product_available": False,
    }
    script = f"""    render({json.dumps(stopped, ensure_ascii=False)});
    const action = document.getElementById("statusAction");
    action.focus();
    const actionRect = action.getBoundingClientRect();
    const result = {{
      statusTitle: document.getElementById("statusTitle").textContent,
      statusDetail: document.getElementById("statusDetail").textContent,
      statusActionText: action.textContent.trim(),
      statusActionHidden: action.hidden,
      statusActionHref: action.getAttribute("href"),
      managerHref: document.getElementById("manageLink").getAttribute("href"),
      statusActionFocused: document.activeElement === action,
      statusActionWidth: actionRect.width,
      statusActionHeight: actionRect.height,
      disabledWorkspaces: document.querySelectorAll(".workspace-control:disabled").length,
      connectionText: document.getElementById("connectionText").textContent
    }};
    document.body.setAttribute("data-product-recovery-probe", JSON.stringify(result));"""
    page = _write_product_fixture(
        tmp_path,
        page_name=f"product-stopped-{width}x{height}.html",
        startup_script=script,
    )
    value = evaluate_page(
        edge,
        profile=tmp_path / f"edge-product-stopped-profile-{width}-{height}",
        url=page.as_uri(),
        width=width,
        height=height,
        expression=("document.body && document.body.getAttribute('data-product-recovery-probe') || undefined"),
    )
    assert isinstance(value, str)
    return json.loads(value)


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(("width", "height"), [(390, 844), (820, 660)])
@pytest.mark.parametrize("degraded", [False, True])
def test_manager_layout_has_no_overflow_overlap_or_unsafe_repair_path(
    tmp_path: Path,
    width: int,
    height: int,
    degraded: bool,
) -> None:
    probe = _render_with_edge(tmp_path, width=width, height=height, degraded=degraded)

    assert probe["horizontalOverflow"] is False
    assert probe["overlaps"] == []
    assert probe["unnamedButtons"] == 0
    assert probe["clippedButtons"] == 0
    assert probe["diagnosticsDisabled"] is False
    assert probe["primaryDisabled"] is degraded
    assert probe["primaryAction"] == ("start" if degraded else "stop")
    assert probe["primaryText"] == ("▶启动" if degraded else "■停止")
    assert probe["overallText"] == ("需要处理" if degraded else "运行正常")
    assert probe["runtimeText"] == "本机安装"
    assert probe["serviceTitle"] == ("小票夹需要修复" if degraded else "小票夹正在运行")


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(("width", "height"), [(820, 660), (1180, 760)])
def test_desktop_product_shell_is_usable_at_supported_app_window_sizes(
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    probe = _render_product_with_edge(tmp_path, width=width, height=height)

    assert probe["horizontalOverflow"] is False
    assert probe["unnamedButtons"] == 0
    assert probe["clippedButtons"] == 0
    assert probe["railFillsWorkspace"] is True
    assert probe["workspaceLabels"] == ["收件", "流水", "往来", "计划", "洞察"]
    assert probe["activeWorkspace"] == "plans"
    assert probe["workspaceTitle"] == "计划"
    assert probe["keyboardWorkspace"] == "plans"
    assert probe["keyboardWorkspaceTitle"] == "计划"
    assert probe["rowCount"] == 2
    assert probe["selectedRows"] == 1
    assert probe["selectedTitle"] == "工资"
    assert probe["inspectorFieldCount"] == 1
    assert probe["shellPathStable"] is True
    assert probe["windowOpenCalls"] == 0
    assert any(str(call).startswith("/api/product/plans") for call in probe["fetchCalls"])
    assert probe["inboxFormVisible"] is True
    assert probe["inboxCurrencyLabel"] == "金额（CNY · ¥）"
    assert probe["inboxAmountValue"] == "18.80"
    assert probe["inboxHeaders"] == [
        "待整理商家",
        "分类 / 缺口",
        "处理状态",
        "待确认金额",
        "收到 / 消费时间",
    ]
    assert probe["transactionHeaders"] == [
        "入账商家",
        "分类 / 来源",
        "入账状态",
        "已入账金额",
        "消费时间",
    ]
    assert probe["obligationHeaders"] == [
        "往来对象",
        "当前关系",
        "结清状态",
        "待清算",
        "最近更新",
    ]
    assert probe["ignoreConfirmationOpened"] is True
    assert probe["ignoreCancellationPreventedCommand"] is True
    assert probe["planGroupCount"] == 4
    assert "7月21日" in probe["planDateText"]
    assert ":" not in probe["planDateText"]
    assert probe["refreshPreservedContext"] is True
    assert probe["refreshRestoredContext"] is True
    assert probe["filterEmptyPanelVisible"] is True
    assert probe["filterClearedFromEmptyState"] is True
    assert probe["insightFactVisible"] is True
    assert probe["insightAttentionCount"] == 1
    assert probe["insightQualityCount"] == 0
    assert probe["unpairConfirmationOpened"] is True
    assert probe["unpairCancellationPreventedRequest"] is True
    assert len(probe["commandCalls"]) == 1
    command = probe["commandCalls"][0]
    assert command["url"].startswith("/api/product/inbox/expenses/fixture-inbox-first/commands?ledger_id=owner")
    assert command["method"] == "POST"
    assert command["idempotencyKey"]
    assert command["controlToken"] == "__CONTROL_TOKEN__"
    assert command["payload"] == {
        "action": "confirm",
        "expected_row_version": 1,
    }
    assert probe["switchCalls"] == [
        {
            "ledgerId": "family",
            "controlToken": "__CONTROL_TOKEN__",
        }
    ]
    assert probe["keyboardRefreshAddedCall"] is True
    assert probe["connectionText"] == "已同步"
    assert probe["disabledWorkspaces"] == 0
    assert probe["ledgerOptionCount"] == 2
    assert probe["selectedLedger"] == "family"
    assert probe["ledgerPreservedAcrossWorkspace"] is True
    assert probe["roleNote"] == "家庭账本 · 只读"
    assert probe["workspaceContentWidth"] > 0
    if width <= 1007:
        assert probe["inspectorWidth"] == 0
    else:
        assert probe["inspectorWidth"] >= 250
    assert probe["minimumSupportingFontPx"] >= 12


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(
    ("width", "expected_size_class", "expected_compact"),
    [
        (640, "small", True),
        (641, "medium", True),
        (1007, "medium", True),
        (1008, "large", False),
    ],
)
def test_desktop_product_shell_tracks_official_windows_window_breakpoints(
    tmp_path: Path,
    width: int,
    expected_size_class: str,
    expected_compact: bool,
) -> None:
    probe = _render_product_with_edge(tmp_path, width=width, height=760)

    assert probe["viewportWidth"] == width
    assert probe["windowsSizeClass"] == expected_size_class
    assert probe["compactShell"] is expected_compact
    assert probe["horizontalOverflow"] is False
    assert probe["clippedButtons"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize("width", [320, 390, 480, 641, 820, 1007])
def test_desktop_product_compact_window_keeps_main_stage_and_uses_inspector_drawer(
    tmp_path: Path,
    width: int,
) -> None:
    probe = _render_product_with_edge(tmp_path, width=width, height=760)
    drawer = probe["inspectorDrawer"]

    assert probe["windowsSizeClass"] == ("small" if width <= 640 else "medium")
    assert probe["horizontalOverflow"] is False
    assert probe["unnamedButtons"] == 0
    assert probe["clippedButtons"] == 0
    assert drawer["applicable"] is True
    assert drawer["stageWidthClosed"] + drawer["railWidth"] == pytest.approx(
        probe["viewportWidth"],
        abs=1,
    )
    assert drawer["stageWidthWhileOpen"] == pytest.approx(
        drawer["stageWidthClosed"],
        abs=1,
    )
    assert drawer["openWidth"] == pytest.approx(drawer["stageWidthClosed"], abs=1)
    assert drawer["openedByClick"] is True
    assert drawer["role"] == "dialog"
    assert drawer["modal"] == "true"
    assert drawer["closeButtonFocused"] is True
    assert drawer["closedByButton"] is True
    assert drawer["focusRestoredAfterButton"] is True
    assert drawer["openedByEnter"] is True
    assert drawer["tabWrappedToClose"] is True
    assert drawer["closedByEscape"] is True
    assert drawer["focusRestoredAfterEscape"] is True
    assert probe["inspectorWidth"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(("width", "height"), [(820, 660), (1180, 760)])
def test_stopped_desktop_product_offers_in_place_manager_recovery(
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    probe = _render_stopped_product_with_edge(tmp_path, width=width, height=height)

    assert probe["statusTitle"] == "小票夹服务已停止"
    assert probe["statusDetail"] == "进入系统管理启动服务或导出诊断。"
    assert probe["statusActionText"] == "打开系统管理"
    assert probe["statusActionHidden"] is False
    assert probe["statusActionHref"] == "/"
    assert probe["statusActionHref"] == probe["managerHref"]
    assert probe["statusActionFocused"] is True
    assert probe["statusActionWidth"] > 0
    assert probe["statusActionHeight"] >= 38
    assert probe["disabledWorkspaces"] == 5
    assert probe["connectionText"] == "服务已停止"


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge stale-data gate")
def test_product_preserves_stale_dom_on_transient_failure_and_clears_on_auth_boundary(
    tmp_path: Path,
) -> None:
    probe = _render_product_fail_closed_probe(tmp_path)

    assert probe["healthy"]["payloadNull"] is False
    assert probe["healthy"]["rows"] == 2
    assert probe["healthy"]["domRows"] == 2
    assert probe["healthy"]["inspectorValue"] != "—"
    assert probe["healthy"]["pendingCommandNull"] is False

    trusted_data_fields = (
        "payloadNull",
        "payloadWorkspace",
        "payloadGeneratedAt",
        "rows",
        "rowKeys",
        "visibleRows",
        "visibleRowKeys",
        "selectedKey",
        "ledgerId",
        "pendingCommandNull",
        "pendingCommand",
        "domRows",
        "domTitles",
        "inspectorTitle",
        "inspectorValue",
        "inspectorFields",
        "roleNote",
        "commandAmount",
        "ledgerOptions",
    )
    for state_name in ("serviceUnavailable", "networkFailure"):
        state_probe = probe[state_name]
        assert {field: state_probe[field] for field in trusted_data_fields} == {
            field: probe["healthy"][field] for field in trusted_data_fields
        }
        last_sync = probe["healthy"]["syncNote"].removeprefix("最近同步 · ")
        assert state_probe["syncNote"] == (f"同步失败 · 正在显示上次可信内容 · 最后同步 {last_sync}")
        assert state_probe["connectionText"] == (f"同步失败 · 显示上次内容 · 最后同步 {last_sync}")
        assert state_probe["statusPanelHidden"] is True
        assert state_probe["refreshDisabled"] is False

    for state_name in ("unauthorized", "forbidden", "ledgerChange"):
        state_probe = probe[state_name]
        assert {field: state_probe[field] for field in trusted_data_fields} == {
            "payloadNull": True,
            "payloadWorkspace": "",
            "payloadGeneratedAt": "",
            "rows": 0,
            "rowKeys": [],
            "visibleRows": 0,
            "visibleRowKeys": [],
            "selectedKey": "",
            "ledgerId": "",
            "pendingCommandNull": True,
            "pendingCommand": None,
            "domRows": 0,
            "domTitles": [],
            "inspectorTitle": "选择一项",
            "inspectorValue": "—",
            "inspectorFields": 0,
            "roleNote": "—",
            "commandAmount": "",
            "ledgerOptions": ["账本未加载"],
        }


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
def test_manager_offline_and_service_action_states_remain_coherent(tmp_path: Path) -> None:
    probe = _render_behavior_probe(tmp_path)

    assert probe["offline"] == {
        "threw": False,
        "primaryDisabled": True,
        "androidDisabled": True,
        "overallText": "管理器离线",
    }
    assert probe["primaryAction"] == "start"
    assert probe["primaryText"] == "▶启动"


def test_layout_probe_retries_a_fresh_edge_session_after_transport_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles: list[Path] = []

    def evaluate_once(_edge: str, *, profile: Path, **_kwargs: object) -> object:
        profiles.append(profile)
        if len(profiles) == 1:
            raise TimeoutError("synthetic DevTools stall")
        return {"ready": True}

    monkeypatch.setattr(_edge_cdp, "_evaluate_page_once", evaluate_once)

    result = evaluate_page(
        "edge.exe",
        profile=tmp_path / "profile",
        url="file:///manager.html",
        width=390,
        height=844,
        expression="window.__layoutProbe",
    )

    assert result == {"ready": True}
    assert profiles == [
        tmp_path / "profile" / "attempt-1",
        tmp_path / "profile" / "attempt-2",
    ]


def test_layout_probe_does_not_retry_a_semantic_assertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles: list[Path] = []

    def evaluate_once(_edge: str, *, profile: Path, **_kwargs: object) -> object:
        profiles.append(profile)
        raise AssertionError("layout probe did not become available")

    monkeypatch.setattr(_edge_cdp, "_evaluate_page_once", evaluate_once)

    with pytest.raises(AssertionError, match="layout probe did not become available"):
        evaluate_page(
            "edge.exe",
            profile=tmp_path / "profile",
            url="file:///manager.html",
            width=390,
            height=844,
            expression="window.__layoutProbe",
        )

    assert profiles == [tmp_path / "profile" / "attempt-1"]


def test_edge_teardown_reaps_process_when_websocket_cleanup_fails(monkeypatch) -> None:
    events: list[str] = []

    class FailingWebSocket:
        def request(self, method: str) -> None:
            events.append(method)

        def close(self) -> None:
            events.append("socket-close")
            raise OSError("synthetic close failure")

    class StubbornProcess:
        def __init__(self) -> None:
            self.wait_count = 0

        def wait(self, timeout: int) -> int:
            self.wait_count += 1
            events.append(f"wait-{self.wait_count}")
            if self.wait_count < 3:
                raise _edge_cdp.subprocess.TimeoutExpired("edge", timeout)
            return 0

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(_edge_cdp, "_WebSocket", lambda _endpoint: FailingWebSocket())

    _edge_cdp._stop_edge(  # noqa: SLF001 - teardown failure contract
        StubbornProcess(),  # type: ignore[arg-type]
        page=FailingWebSocket(),  # type: ignore[arg-type]
        browser_endpoint="ws://127.0.0.1:9222/devtools/browser/test",
    )

    assert events == [
        "socket-close",
        "Browser.close",
        "socket-close",
        "wait-1",
        "terminate",
        "wait-2",
        "kill",
        "wait-3",
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
def test_manager_shutdown_state_closes_real_edge_app_window(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Windows Desktop Manager gate"
    status = _status(degraded=False)
    status["manager_shutdown_requested"] = True
    source = _UI_HTML.read_text(encoding="utf-8")
    rendered = source.replace(_STARTUP_SCRIPT, f"    render({json.dumps(status)});")
    rendered = rendered.replace("setTimeout(() => window.close(), 50)", "setTimeout(() => window.close(), 1500)")
    page = tmp_path / "manager-shutdown.html"
    page.write_text(rendered, encoding="utf-8")

    wait_for_app_window_close(
        edge,
        profile=tmp_path / "edge-profile-shutdown",
        url=page.as_uri(),
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
def test_production_edge_process_tracks_the_visible_window_lifetime(tmp_path: Path) -> None:
    assert discover_edge_executable() is not None
    page = tmp_path / "close-window.html"
    page.write_text(
        "<!doctype html><title>Ticketbox close test</title><script>setTimeout(() => window.close(), 2000)</script>",
        encoding="utf-8",
    )

    window = desktop_shell.open_app_window(
        page.as_uri(),
        profile=tmp_path / "production-edge-profile",
    )

    assert window is not None
    assert window.is_open()
    time.sleep(0.75)
    assert window.is_open(), "Edge launcher exited before the visible app window"
    window.process.wait(timeout=10)
    assert window.is_open() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
def test_host_can_close_real_edge_when_the_page_never_acknowledges(tmp_path: Path) -> None:
    assert discover_edge_executable() is not None
    page = tmp_path / "stalled-window.html"
    page.write_text("<!doctype html><title>Ticketbox stalled test</title>", encoding="utf-8")

    window = desktop_shell.open_app_window(
        page.as_uri(),
        profile=tmp_path / "stalled-edge-profile",
    )

    assert window is not None
    assert window.is_open()
    assert window.close(timeout=5) is True
    assert window.is_open() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
def test_production_window_session_owns_every_reopened_edge_process(tmp_path: Path) -> None:
    assert discover_edge_executable() is not None
    page = tmp_path / "multi-window.html"
    page.write_text("<!doctype html><title>Ticketbox multi-window test</title>", encoding="utf-8")
    opened: list[desktop_shell.EdgeAppWindow] = []

    def open_window(url: str, *, profile: Path) -> desktop_shell.EdgeAppWindow | None:
        window = desktop_shell.open_app_window(url, profile=profile)
        if window is not None:
            opened.append(window)
        return window

    profile_root = tmp_path / "production-edge-session"
    windows = ManagerWindowSession(page.as_uri(), profile_root, opener=open_window)
    try:
        assert windows.open() is True
        assert windows.open() is True
        time.sleep(1)
        assert len(opened) == 2
        assert all(window.is_open() for window in opened)
        assert windows.close_all() is True
        assert all(not window.is_open() for window in opened)
    finally:
        windows.shutdown()

    assert not profile_root.exists()
