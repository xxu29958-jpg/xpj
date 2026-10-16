"""Shared preparation for the existing  manager ui consumers."""

from __future__ import annotations

from pathlib import Path

_UI_HTML = Path(__file__).resolve().parents[1] / "backend_manager" / "ui.html"


_STARTUP_SCRIPT = "    refresh();\n    setInterval(refresh, 2500);"


def _public_connectivity(*, degraded: bool) -> dict[str, object]:
    rows = [
        ("小票夹后端", "unknown" if degraded else "unknown", "公网连接状态未知"),
        ("Windows 服务", "unknown", "未知"),
        ("Cloudflare Edge", "unknown", "未知"),
        ("本机源站", "unknown" if degraded else "healthy", "未知" if degraded else "小票夹源站正常"),
        ("公网端点", "unconfigured", "未配置公网地址"),
        ("公开边界", "unknown", "尚未完整检查"),
        ("最近观察", "stale", "尚无观察"),
        ("cloudflared 版本", "informational", "未知"),
        ("所有权", "unknown", "未知"),
    ]
    return {
        "schema": "ticketbox-public-connectivity-v1",
        "overall": "unknown",
        "code": "public_connectivity_unknown",
        "summary": "公网连接状态未知",
        "next_step": "刷新本机状态，必要时运行完整公网检查。",
        "ownership": "unknown",
        "service": "unknown",
        "connector": "unknown",
        "origin": "unknown" if degraded else "healthy",
        "public": "unconfigured",
        "boundary": "unknown",
        "freshness": "stale",
        "managed_action": "unavailable",
        "observed_at": None,
        "public_checked_at": None,
        "in_progress": False,
        "cloudflared_version": None,
        "connection_count": None,
        "service_identity_match": None,
        "binary_identity_match": None,
        "tunnel_identity_match": None,
        "supported_actions": ["refresh", "full_check", "export_diagnostics"],
        "detail_rows": [{"label": label, "state": state, "text": text} for label, state, text in rows],
    }


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
        "public_connectivity": _public_connectivity(degraded=degraded),
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


def _render_probe_page(tmp_path: Path, name: str, script: str) -> Path:
    source = _UI_HTML.read_text(encoding="utf-8")
    assert source.count(_STARTUP_SCRIPT) == 1
    page = tmp_path / name
    page.write_text(source.replace(_STARTUP_SCRIPT, script), encoding="utf-8")
    return page
