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
_STARTUP_SCRIPT = "    refresh();\n    setInterval(refresh, 2500);"


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
        "version": "1.2.0",
        "service_controls_available": False,
        "log": ["运行投影不可用；未使用启动时的旧安装信息。"] if degraded else ["服务正常。"],
        "control_error": "安装信息已变化或不可用；请修复或重新安装小票夹。" if degraded else None,
        "action_notice": None,
        "diagnostic_bundle_file": None,
        "manager_shutdown_requested": False,
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
      primaryHidden: document.getElementById("primaryAction").hidden,
      restartHidden: document.getElementById("restartAction").hidden,
      dataProtectionHidden: document.getElementById("dataProtectionCard").hidden,
      importExportDisabled: document.getElementById("importExportAction").disabled,
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
    script = f"""    (async () => {{
      const healthy = {json.dumps(healthy, ensure_ascii=False)};
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
      document.body.setAttribute("data-behavior-probe", JSON.stringify({{offline}}));
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
    assert probe["primaryDisabled"] is True
    assert probe["primaryHidden"] is True
    assert probe["restartHidden"] is True
    # The data protection card no longer hides with service controls; its
    # product entry is disabled exactly when the product is not ready.
    assert probe["dataProtectionHidden"] is False
    assert probe["importExportDisabled"] is degraded
    assert probe["primaryAction"] == ("start" if degraded else "stop")
    assert probe["primaryText"] == ("▶启动" if degraded else "■停止")
    assert probe["overallText"] == ("需要处理" if degraded else "运行正常")
    assert probe["runtimeText"] == "本机安装"
    assert probe["serviceTitle"] == ("小票夹需要修复" if degraded else "小票夹正在运行")


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
def test_manager_offline_state_remains_coherent(tmp_path: Path) -> None:
    probe = _render_behavior_probe(tmp_path)

    assert probe["offline"] == {
        "threw": False,
        "primaryDisabled": True,
        "androidDisabled": True,
        "overallText": "管理器离线",
    }


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
        "<!doctype html><title>Ticketbox close test</title>"
        "<script>setTimeout(() => window.close(), 2000)</script>",
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


# ── Served /web through the Manager BFF (real backend layout probes) ────────

from tests._real_backend import (  # noqa: E402
    CredentialStores,
    RealBackend,
    make_controller,
    make_manager,
    manager_post_json,
    serving,
)

pytest_plugins = ["tests._real_backend"]

_SERVED_WEB_PROBE = """
(() => {
  const atWeb = location.pathname === "/web" || location.pathname === "/web/pending";
  if (!atWeb || !document.querySelector("#main-content")) return undefined;
  const interactive = [...document.querySelectorAll("button, a, input, select, textarea")];
  const visible = interactive.filter((el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  });
  return JSON.stringify({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ledgerChip: Boolean(document.querySelector(".ledger-role-chip")),
    hasOwnerLedger: document.body.innerText.includes("我的小票夹"),
    unnamedControls: visible.filter((el) =>
      !(el.getAttribute("aria-label") || (el.textContent || "").trim() || (el.value || "").trim())
    ).length,
    href: location.href
  });
})()
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(("width", "height"), [(1180, 760), (820, 660)])
def test_served_web_layout_through_manager_bff(
    tmp_path: Path,
    real_backend: RealBackend,
    width: int,
    height: int,
) -> None:
    """The BFF-served /web stays usable at both supported app-window sizes."""
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the served-/web layout gate"
    stores = CredentialStores()
    manager = make_manager(make_controller(real_backend.port, stores))
    manager_origin = f"http://127.0.0.1:{manager.server_address[1]}"

    with serving(manager):
        status, projection = manager_post_json(
            manager.server_address[1],
            "/api/product/pair",
            {"pairing_code": real_backend.fresh_pairing_code()},
            origin=manager_origin,
        )
        assert status == 200, projection
        bootstrap_path = tmp_path / f"served-web-{width}x{height}" / "bootstrap.html"
        bootstrap_url = manager.prepare_web_bootstrap(bootstrap_path)
        value = evaluate_page(
            edge,
            profile=tmp_path / f"edge-served-web-{width}x{height}",
            url=bootstrap_url,
            width=width,
            height=height,
            expression=_SERVED_WEB_PROBE,
        )

    assert not bootstrap_path.exists()
    assert isinstance(value, str)
    probe = json.loads(value)
    assert probe["overflow"] is False
    assert probe["ledgerChip"] is True
    assert probe["hasOwnerLedger"] is True
    assert probe["unnamedControls"] == 0
    assert stores.sessions


# ── Manager product card: hidden-authority + live ledger switching (218-E) ──


def _product_status() -> dict[str, object]:
    status = _status(degraded=False)
    status["product_available"] = True
    status["product_url"] = "/web"
    return status


_PRODUCT_SESSION = {
    "configured": True,
    "account_name": "我",
    "ledger_id": "owner",
    "ledger_name": "我的小票夹",
    "device_name": "小票夹 Desktop",
    "role": "owner",
    "expires_at": None,
}
_PRODUCT_LEDGERS = {
    "ledgers": [
        {"ledger_id": "owner", "name": "我的小票夹", "role": "owner", "is_default": True, "is_current": True},
        {"ledger_id": "family", "name": "家庭账本", "role": "viewer", "is_default": False, "is_current": False},
    ]
}


def _render_probe_page(tmp_path: Path, name: str, script: str) -> Path:
    source = _UI_HTML.read_text(encoding="utf-8")
    assert source.count(_STARTUP_SCRIPT) == 1
    page = tmp_path / name
    page.write_text(source.replace(_STARTUP_SCRIPT, script), encoding="utf-8")
    return page


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
@pytest.mark.parametrize(("width", "height"), [(1180, 760), (820, 660)])
def test_product_card_visibility_matrix_is_hidden_authoritative(
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    """Unpaired shows pair form only; paired shows manage + /web link only."""
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the product-card visibility gate"
    script = f"""    (async () => {{
      const healthy = {json.dumps(_product_status(), ensure_ascii=False)};
      const pairedSession = {json.dumps(_PRODUCT_SESSION, ensure_ascii=False)};
      const ledgers = {json.dumps(_PRODUCT_LEDGERS, ensure_ascii=False)};
      const displayOf = (id) => getComputedStyle(document.getElementById(id)).display;
      window.fetch = async (url) => {{
        if (url === "/api/product/session") return {{status: 200, ok: true, json: async () => ({{configured: false}})}};
        return {{status: 200, ok: true, json: async () => healthy}};
      }};
      render(healthy);
      await loadProductSession();
      const unpaired = {{
        link: displayOf("productHomeLink"),
        pair: displayOf("productPairGroup"),
        manage: displayOf("productManageGroup"),
        importExportDisabled: $("importExportAction").disabled
      }};
      window.fetch = async (url) => {{
        if (url === "/api/product/session") return {{status: 200, ok: true, json: async () => pairedSession}};
        if (url === "/api/product/ledgers") return {{status: 200, ok: true, json: async () => ledgers}};
        return {{status: 200, ok: true, json: async () => healthy}};
      }};
      await loadProductSession();
      await loadProductLedgers();
      const paired = {{
        link: displayOf("productHomeLink"),
        pair: displayOf("productPairGroup"),
        manage: displayOf("productManageGroup"),
        importExportDisabled: $("importExportAction").disabled,
        options: [...$("ledgerSelect").options].map((option) => option.value)
      }};
      document.body.setAttribute("data-visibility-probe", JSON.stringify({{unpaired, paired}}));
    }})();"""
    page = _render_probe_page(tmp_path, f"product-visibility-{width}x{height}.html", script)
    value = evaluate_page(
        edge,
        profile=tmp_path / f"edge-product-visibility-{width}x{height}",
        url=page.as_uri(),
        width=width,
        height=height,
        expression="document.body && document.body.getAttribute('data-visibility-probe') || undefined",
    )
    assert isinstance(value, str)
    probe = json.loads(value)
    assert probe["unpaired"] == {
        "link": "none",
        "pair": "flex",
        "manage": "none",
        "importExportDisabled": True,
    }
    # Chromium reports inline-flex's used display as "flex"; the contract is
    # "link visible, pair form gone, manage group visible".
    assert probe["paired"]["link"] in ("inline-flex", "flex")
    assert probe["paired"]["pair"] == "none"
    assert probe["paired"]["manage"] == "flex"
    assert probe["paired"]["importExportDisabled"] is False
    assert probe["paired"]["options"] == ["owner", "family"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
def test_ledger_select_keeps_dirty_selection_until_successful_switch(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the ledger-switch behavior gate"
    script = f"""    (async () => {{
      const healthy = {json.dumps(_product_status(), ensure_ascii=False)};
      const baseSession = {json.dumps(_PRODUCT_SESSION, ensure_ascii=False)};
      const ledgers = {json.dumps(_PRODUCT_LEDGERS, ensure_ascii=False)};
      let switched = false;
      window.fetch = async (url) => {{
        if (url === "/api/product/session") {{
          return {{
            status: 200,
            ok: true,
            json: async () => (switched
              ? {{...baseSession, ledger_id: "family", ledger_name: "家庭账本", role: "viewer"}}
              : baseSession)
          }};
        }}
        if (url === "/api/product/ledgers") return {{status: 200, ok: true, json: async () => ledgers}};
        if (url === "/api/status") return {{status: 200, ok: true, json: async () => healthy}};
        if (url === "/api/product/ledger/switch") {{
          switched = true;
          return {{status: 200, ok: true, json: async () => ({{configured: true}})}};
        }}
        throw new Error("unexpected " + url);
      }};
      await refresh();
      const initialOptions = [...$("ledgerSelect").options].map((option) => option.value);
      const select = $("ledgerSelect");
      select.value = "family";
      select.dispatchEvent(new Event("change", {{bubbles: true}}));
      const afterPick = {{value: select.value, switchDisabled: $("switchAction").disabled}};
      await refresh();
      const afterTick = {{value: select.value, switchDisabled: $("switchAction").disabled}};
      await switchProductLedger();
      const afterSwitch = {{value: select.value, switchDisabled: $("switchAction").disabled}};
      await refresh();
      const afterSettle = {{value: select.value, switchDisabled: $("switchAction").disabled}};
      document.body.setAttribute("data-dirty-probe", JSON.stringify({{
        initialOptions, afterPick, afterTick, afterSwitch, afterSettle
      }}));
    }})();"""
    page = _render_probe_page(tmp_path, "product-dirty-selection.html", script)
    value = evaluate_page(
        edge,
        profile=tmp_path / "edge-product-dirty-selection",
        url=page.as_uri(),
        width=820,
        height=660,
        expression="document.body && document.body.getAttribute('data-dirty-probe') || undefined",
    )
    assert isinstance(value, str)
    probe = json.loads(value)
    # The initial page load fills the dropdown (defect 2b).
    assert probe["initialOptions"] == ["owner", "family"]
    # A differing user selection survives the refresh tick (defect 2a).
    assert probe["afterPick"] == {"value": "family", "switchDisabled": False}
    assert probe["afterTick"] == {"value": "family", "switchDisabled": False}
    # A successful switch clears the dirty state and follows the new session.
    assert probe["afterSwitch"] == {"value": "family", "switchDisabled": True}
    assert probe["afterSettle"] == {"value": "family", "switchDisabled": True}


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
def test_ledger_list_refreshes_on_cadence_without_clobbering_dirty_selection(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the ledger-list cadence gate"
    script = f"""    (async () => {{
      const healthy = {json.dumps(_product_status(), ensure_ascii=False)};
      const session = {json.dumps(_PRODUCT_SESSION, ensure_ascii=False)};
      const ledgers = {json.dumps(_PRODUCT_LEDGERS, ensure_ascii=False)};
      let ledgerFetches = 0;
      window.fetch = async (url) => {{
        if (url === "/api/product/session") return {{status: 200, ok: true, json: async () => session}};
        if (url === "/api/product/ledgers") {{
          ledgerFetches += 1;
          return {{status: 200, ok: true, json: async () => ledgers}};
        }}
        if (url === "/api/status") return {{status: 200, ok: true, json: async () => healthy}};
        throw new Error("unexpected " + url);
      }};
      await refresh();
      const afterFirst = ledgerFetches;
      await refresh();
      const afterSecond = ledgerFetches;
      for (let tick = 0; tick < 10; tick += 1) await refresh();
      const afterElevenTicks = ledgerFetches;
      await refresh();
      const afterTwelveTicks = ledgerFetches;
      const select = $("ledgerSelect");
      select.value = "family";
      select.dispatchEvent(new Event("change", {{bubbles: true}}));
      for (let tick = 0; tick < 12; tick += 1) await refresh();
      const afterCadenceWithDirty = {{
        fetches: ledgerFetches,
        value: select.value,
        switchDisabled: $("switchAction").disabled
      }};
      document.body.setAttribute("data-cadence-probe", JSON.stringify({{
        afterFirst, afterSecond, afterElevenTicks, afterTwelveTicks, afterCadenceWithDirty
      }}));
    }})();"""
    page = _render_probe_page(tmp_path, "product-ledger-cadence.html", script)
    value = evaluate_page(
        edge,
        profile=tmp_path / "edge-product-ledger-cadence",
        url=page.as_uri(),
        width=820,
        height=660,
        expression="document.body && document.body.getAttribute('data-cadence-probe') || undefined",
    )
    assert isinstance(value, str)
    probe = json.loads(value)
    # Initial load fills the list; ordinary ticks do not refetch; the 12th tick does.
    assert probe["afterFirst"] == 1
    assert probe["afterSecond"] == 1
    assert probe["afterElevenTicks"] == 1
    assert probe["afterTwelveTicks"] == 2
    # The cadence refresh keeps the dirty selection alive and switchable.
    assert probe["afterCadenceWithDirty"] == {
        "fetches": 3,
        "value": "family",
        "switchDisabled": False,
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge consumer gate")
def test_product_card_role_follows_live_membership_and_handles_vanished_ledger(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the live-role rendering gate"
    script = f"""    (async () => {{
      const healthy = {json.dumps(_product_status(), ensure_ascii=False)};
      const session = {{configured: true, account_name: "我", ledger_id: "owner", ledger_name: "我的小票夹", device_name: "小票夹 Desktop", role: "owner", expires_at: null}};
      const demotedLedgers = {{ledgers: [
        {{ledger_id: "owner", name: "我的小票夹", role: "viewer", is_default: true, is_current: true}},
        {{ledger_id: "family", name: "家庭账本", role: "member", is_default: false, is_current: false}}
      ]}};
      const vanishedLedgers = {{ledgers: [
        {{ledger_id: "family", name: "家庭账本", role: "member", is_default: false, is_current: false}}
      ]}};
      let ledgersPayload = demotedLedgers;
      window.fetch = async (url) => {{
        if (url === "/api/product/session") return {{status: 200, ok: true, json: async () => session}};
        if (url === "/api/product/ledgers") return {{status: 200, ok: true, json: async () => ledgersPayload}};
        if (url === "/api/status") return {{status: 200, ok: true, json: async () => healthy}};
        throw new Error("unexpected " + url);
      }};
      await loadProductSession();
      await loadProductLedgers();
      const demoted = {{
        state: document.getElementById("productState").textContent,
        manageHidden: document.getElementById("productManageGroup").hidden,
        pairHidden: document.getElementById("productPairGroup").hidden
      }};
      ledgersPayload = vanishedLedgers;
      productLedgers = [];
      await loadProductSession();
      await loadProductLedgers();
      const vanished = {{
        state: document.getElementById("productState").textContent,
        manageHidden: document.getElementById("productManageGroup").hidden,
        pairHidden: document.getElementById("productPairGroup").hidden,
        linkHidden: document.getElementById("productHomeLink").hidden
      }};
      document.body.setAttribute("data-live-role-probe", JSON.stringify({{demoted, vanished}}));
    }})();"""
    page = _render_probe_page(tmp_path, "product-live-role.html", script)
    value = evaluate_page(
        edge,
        profile=tmp_path / "edge-product-live-role",
        url=page.as_uri(),
        width=820,
        height=660,
        expression="document.body && document.body.getAttribute('data-live-role-probe') || undefined",
    )
    assert isinstance(value, str)
    probe = json.loads(value)
    # A demotion arrives via the 30s ledger refresh: the card shows 只读 even
    # though WinCred persisted 拥有者 at pair time.
    assert "只读" in probe["demoted"]["state"]
    assert "拥有者" not in probe["demoted"]["state"]
    assert probe["demoted"]["manageHidden"] is False
    # The bound ledger vanishing from memberships shows the re-pair state,
    # never a phantom owner role.
    assert "原绑定已失效" in probe["vanished"]["state"]
    assert probe["vanished"]["manageHidden"] is True
    assert probe["vanished"]["pairHidden"] is False
    assert probe["vanished"]["linkHidden"] is True
