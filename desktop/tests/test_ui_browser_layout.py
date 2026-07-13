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
        "service_controls_available": not degraded,
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
