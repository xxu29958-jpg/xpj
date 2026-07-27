"""Security-sensitive static contracts for the localhost manager UI."""

from __future__ import annotations

from pathlib import Path


def test_backend_log_is_rendered_as_text_not_html() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "row.textContent = line" in html
    assert "运行诊断" in html
    assert "实时日志" not in html
    assert "log.replaceChildren" in html
    assert "log.innerHTML" not in html


def test_narrow_window_switches_task_workbench_to_one_column() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "@media (max-width: 700px)" in html
    assert ".task-grid { grid-template-columns: 1fr; }" in html


def test_status_refresh_is_single_flight() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "if (refreshInFlight) return" in html
    assert "refreshInFlight = false" in html
    assert 'fetch("/api/status", {headers:{"X-Control-Token": window.CONTROL_TOKEN}})' in html


def test_installer_shutdown_state_closes_only_the_manager_window() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "s.manager_shutdown_requested" in html
    assert "setTimeout(() => window.close(), 50)" in html
    assert "服务可能暂时不可用" in html
    assert "小票夹会继续在后台运行" not in html
    assert "Windows 服务需要修复" not in html


def test_actions_are_single_flight_and_availability_is_reapplied_from_status() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "if (actionInFlight) return" in html
    assert "applyActionAvailability(latestStatus)" in html
    assert 'document.querySelectorAll(".owner-action")' in html
    assert 'response.status === 409' in html
    assert 'button.disabled = false' not in html


def test_primary_workbench_uses_real_tasks_without_fake_qr_or_token_copy() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert 'data-action="start" onclick="act(this.dataset.action, this)"' in html
    for action in (
        "open_pairing",
        "open_upload_links",
        "open_backups",
        "export_diagnostics",
        "open_diagnostics",
    ):
        assert action in html
    assert "扫码连手机" not in html
    assert '<div class="qr"' not in html
    assert "端口 · PID" not in html
    assert "run_installer" not in html


def test_owner_recovery_is_a_distinct_human_readable_state() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert 's.owner_state === "recovery_required"' in html
    assert "需要恢复身份" in html
    assert "缺少可用拥有者身份" in html
    assert "管理器不能自动重建身份" in html


def test_installer_recovery_guard_is_not_rendered_as_healthy_product_access() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert 's.runtime_access_state === "repair_required"' in html
    assert "安装维护尚未完成" in html
    assert "重新运行可信安装包" in html


def test_local_backend_health_does_not_promise_mobile_reachability() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert 's.android_binding_state !== "configured_unverified"' in html
    assert 's.iphone_upload_state !== "configured_unverified"' in html
    assert "电脑端运行正常；手机连接尚未配置。" in html
    assert "手机连接、上传和网页管理均可使用。" not in html


def test_manager_package_ships_only_ui_html_without_product_assets() -> None:
    spec = (Path(__file__).parents[1] / "packaging" / "ticketbox-manager.spec").read_text(encoding="utf-8")

    assert '"ui.html"' in spec or "'ui.html'" in spec
    assert "product.html" not in spec
    assert "product.css" not in spec
    assert "product.js" not in spec
