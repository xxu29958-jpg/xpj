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


def test_public_connectivity_card_is_projection_driven_and_read_only() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    for derived_axis in (
        "projection.service ===",
        "projection.connector ===",
        "projection.origin ===",
        "projection.public ===",
        "projection.boundary ===",
    ):
        assert derived_axis not in html

    card_start = html.index('<section class="connectivity-card"')
    card_end = html.index("</section>", card_start)
    card = html[card_start:card_end]
    for forbidden in ("安装", "启动", "停止", "重启", "修复", "更新", "UAC"):
        assert forbidden not in card
    for forbidden_action in (
        "install_cloudflared",
        "start_cloudflared",
        "stop_cloudflared",
        "restart_cloudflared",
        "repair_cloudflared",
        "update_cloudflared",
    ):
        assert forbidden_action not in html


def test_primary_workbench_uses_real_tasks_without_fake_qr_or_token_copy() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert 'data-action="start" onclick="act(this.dataset.action, this)"' in html
    for action in (
        "open_pairing",
        "open_upload_links",
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

    # Local code generation is available without a phone URL; mobile status
    # still follows its own configuration (the real Edge entry test covers it).
    assert 's.iphone_upload_state !== "configured_unverified"' in html
    assert "电脑端运行正常；手机连接尚未配置。" in html
    assert "手机连接、上传和网页管理均可使用。" not in html


def test_manager_package_ships_only_ui_html_without_product_assets() -> None:
    spec = (Path(__file__).parents[1] / "packaging" / "ticketbox-manager.spec").read_text(encoding="utf-8")

    assert '"ui.html"' in spec or "'ui.html'" in spec
    assert "product.html" not in spec
    assert "product.css" not in spec
    assert "product.js" not in spec


def test_data_protection_card_exposes_only_real_capabilities() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    # The only current user capability is import/export. Backup and restore
    # lifecycle remain HOLD, so the Manager must not advertise either one.
    assert "数据保护" in html
    assert "导入与导出" in html
    assert 'window.location.assign("/web/import")' in html
    assert "查看备份记录" not in html
    assert "open_backups" not in html
    assert "恢复功能当前未开放" not in html
    assert "完整备份" not in html
    # The card stays visible when service controls are unavailable.
    assert "dataProtectionCard" in html
    assert "maintenanceCard" not in html
    # The retired backup/restore mutations leave no markup, JS, or fetch behind.
    for retired in (
        "立即完整备份",
        "读取备份列表",
        "恢复所选备份",
        "restoreGeneration",
        "backupAction",
        "restoreAction",
        "backupInventoryAction",
        "loadBackupInventory",
        "restoreDataset",
        "/api/backups",
        "/api/restore",
        "restore-actions",
    ):
        assert retired not in html
