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


def test_public_connectivity_card_is_projection_driven_and_read_only() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert '<h2 id="publicConnectivityTitle">公网连接</h2>' in html
    assert '<p class="card-subtitle">由 Cloudflare Tunnel 提供</p>' in html
    assert 'id="publicConnectivitySummary"' in html
    assert 'id="publicConnectivityNextStep"' in html
    assert 'id="publicConnectivityDetails"' in html
    assert "PUBLIC_CONNECTIVITY_ACTIONS" in html
    assert 'refresh: {label: "刷新状态", action: "refresh_public_connectivity"}' in html
    assert 'full_check: {label: "完整检查", action: "run_full_public_connectivity_check"}' in html
    assert 'export_diagnostics: {label: "导出诊断", action: "export_diagnostics"}' in html
    assert ".filter(([key]) => supported.has(key))" in html
    assert "projection.overall" in html
    for derived_axis in (
        "projection.service ===",
        "projection.connector ===",
        "projection.origin ===",
        "projection.public ===",
        "projection.boundary ===",
    ):
        assert derived_axis not in html
    assert "summary.textContent = projection.summary" in html
    assert "nextStep.textContent = projection.next_step" in html
    assert "label.textContent = row.label" in html
    assert "value.textContent = row.text" in html

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


def test_public_connectivity_card_has_keyboard_and_narrow_layout_contracts() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "button:focus-visible" in html
    assert ".connectivity-actions { display: flex; flex-wrap: wrap;" in html
    assert ".connectivity-grid { grid-template-columns: 1fr; }" in html
    assert 'aria-live="polite"' in html


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


def test_hidden_attribute_is_authoritative_over_product_display_rules() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    # .product-actions/.product-link set display:flex; the hidden attribute must
    # still win or pair form, manage group and the /web link all render at once.
    assert "[hidden] { display: none !important; }" in html


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
    # The product entry rides the existing owner-action disable mechanism and
    # is additionally gated on a live product binding — no dead clicks.
    assert 'class="button button-primary owner-action" id="importExportAction" type="button" disabled' in html
    assert '$("importExportAction").disabled' in html
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


def test_product_card_visibility_matrix_and_dirty_selection_are_declared() -> None:
    html = (Path(__file__).parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    # Paired state shows manage + /web link (never the pair form); unpaired or
    # a vanished bound ledger shows the pair form (never manage/link).
    assert 'const showManage = configured && !membershipLost;' in html
    assert '$("productHomeLink").hidden = !(showManage && available);' in html
    assert '$("productPairGroup").hidden = showManage;' in html
    assert '$("productManageGroup").hidden = !showManage;' in html
    assert "原绑定已失效" in html
    # The displayed role follows the live membership row, not the persisted one.
    assert "const role = liveRow ? liveRow.role : productSession.role;" in html
    # A differing user selection is never clobbered by a refresh tick; the
    # dirty flag clears only on a successful product action.
    assert "let ledgerSelectionDirty = false;" in html
    assert "if (!ledgerSelectionDirty) select.value = productSession.ledger_id;" in html
    assert "ledgerSelectionDirty = Boolean(" in html
    assert "ledgerSelectionDirty = false;" in html
    # The ledger list also loads on initial page load, not only after actions.
    assert "productLedgers.length === 0" in html
