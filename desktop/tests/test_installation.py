"""Installed-instance binding and runtime-layout contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager import installation
from backend_manager.installation import (
    InstallationConfigError,
    InstalledLayout,
    WindowsReleaseConfig,
    load_installed_release_config,
    parse_installed_binding,
)

_INSTALL_ID = "11111111-1111-4111-8111-111111111111"


def _release_config() -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name="TicketboxBackendCustom",
        pg_service_name="TicketboxPgCustom",
        service_state_timeout_ms=17_000,
        service_poll_interval_ms=125,
        postgres_ready_timeout_ms=23_000,
        backend_ready_timeout_ms=31_000,
        backend_ready_poll_interval_ms=375,
        backend_health_request_timeout_ms=1_750,
        database_tool_timeout_ms=600_000,
        dataset_backup_helper_timeout_ms=1_800_000,
        dataset_restore_helper_timeout_ms=3_600_000,
        dataset_payload_verification_timeout_ms=1_800_000,
        complete_dataset_cleanup_reserve_ms=3_600_000,
        complete_dataset_backup_timeout_ms=5_400_000,
        complete_dataset_restore_timeout_ms=10_800_000,
    )


def test_legacy_registry_without_binding_is_not_an_installed_instance(monkeypatch) -> None:
    monkeypatch.setattr(installation, "_read_installation_binding", lambda: None)
    monkeypatch.setattr(
        installation,
        "_read_install_dir",
        lambda: (_ for _ in ()).throw(AssertionError("registry is not authority")),
    )
    assert installation.discover_installed_layout() is None


def test_installed_release_config_comes_only_from_binding_layout(tmp_path: Path) -> None:
    layout = InstalledLayout(
        install_dir=tmp_path / "program",
        data_root=tmp_path / "data",
        backend_port=8000,
        pg_port=5432,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        backend_version="1.2.0",
        install_id=_INSTALL_ID,
    )
    retired_config = layout.install_dir / "installer" / "windows-release-config.json"
    retired_config.parent.mkdir(parents=True)
    retired_config.write_text('{"backend_service_name":"RetiredBackendOwner"}', encoding="utf-8")
    release = load_installed_release_config(layout)

    assert release.backend_service_name == "TicketboxBackend"
    assert release.pg_service_name == "TicketboxPg"
    assert release.backend_health_request_timeout_ms == 2_000


def test_helper_timeouts_are_summed_from_reachable_state_machine_phases() -> None:
    release = _release_config()

    start = release.helper_action_phase_budget_seconds("start")
    stop = release.helper_action_phase_budget_seconds("stop")
    restart = release.helper_action_phase_budget_seconds("restart")
    backup = release.helper_action_phase_budget_seconds("backup")
    restore = release.helper_action_phase_budget_seconds("restore")

    assert tuple(start) == (
        "pre_action_contract_validation",
        "postgres_settle_before_start",
        "postgres_start",
        "backend_settle_before_start",
        "backend_start",
        "backend_readiness",
        "watchdog_scheduler_margin",
    )
    assert tuple(stop) == (
        "pre_action_contract_validation",
        "backend_settle_before_stop",
        "backend_stop",
        "post_stop_runtime_validation",
        "watchdog_scheduler_margin",
    )
    assert tuple(restart) == (
        "pre_action_contract_validation",
        "backend_settle_before_stop",
        "backend_stop",
        "post_stop_runtime_validation",
        "postgres_settle_before_start",
        "postgres_start",
        "backend_settle_before_start",
        "backend_start",
        "backend_readiness",
        "watchdog_scheduler_margin",
    )
    assert start["postgres_settle_before_start"] == 23
    assert start["postgres_start"] == 23
    assert start["backend_readiness"] == 32.75
    assert stop["post_stop_runtime_validation"] == 18.75
    assert backup["complete_dataset_backup_owner"] == 9001.75
    assert restore["complete_dataset_restore_owner"] == 14401.75
    assert release.powershell_action_timeout_seconds("backup") == 9001.75
    assert release.powershell_action_timeout_seconds("restore") == 14401.75
    for action, phases in (
        ("start", start),
        ("stop", stop),
        ("restart", restart),
        ("backup", backup),
        ("restore", restore),
    ):
        watchdog = release.helper_watchdog_seconds(action)
        parent = release.helper_parent_timeout_ms(action) / 1000
        assert watchdog == sum(phases.values())
        assert parent > watchdog


def test_helper_phase_budget_rejects_unknown_action() -> None:
    release = _release_config()

    with pytest.raises(InstallationConfigError, match="不支持的服务操作：pause"):
        release.helper_action_phase_budget_seconds("pause")


def test_parse_installed_binding_uses_installation_json_not_registry_dataroot(tmp_path: Path) -> None:
    layout = parse_installed_binding(
        {
            "schema": "ticketbox-installed-instance-v1",
            "install_id": "11111111-1111-4111-8111-111111111111",
            "data_root": str(tmp_path / "data"),
            "active_release_id": "1.2.0",
            "pg_service_name": "TicketboxPg",
            "backend_service_name": "TicketboxBackend",
            "pg_port": 5432,
            "backend_port": 8000,
        },
        str(tmp_path / "program"),
    )
    assert layout.data_root == (tmp_path / "data").resolve()
    assert layout.backend_version == "1.2.0"
    assert layout.installation_id == _INSTALL_ID
    release = load_installed_release_config(layout)
    assert release.backend_service_name == "TicketboxBackend"
    assert release.pg_service_name == "TicketboxPg"
    assert release.backend_health_request_timeout_ms == 2000


def test_discover_installed_layout_requires_binding_and_uses_registry_only_as_locator(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        installation,
        "_read_installation_binding",
        lambda: {
            "schema": "ticketbox-installed-instance-v1",
            "install_id": "11111111-1111-4111-8111-111111111111",
            "data_root": str(tmp_path / "bound-data"),
            "active_release_id": "1.2.0",
            "pg_service_name": "TicketboxPg",
            "backend_service_name": "TicketboxBackend",
            "pg_port": 5432,
            "backend_port": 8000,
        },
    )
    monkeypatch.setattr(
        installation,
        "_read_install_dir",
        lambda: str(tmp_path / "program"),
    )
    layout = installation.discover_installed_layout()
    assert layout is not None
    assert layout.install_dir == (tmp_path / "program").resolve()
    assert layout.data_root == (tmp_path / "bound-data").resolve()
    assert layout.backend_service_name == "TicketboxBackend"
