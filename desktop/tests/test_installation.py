"""Installer registry parsing contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend_manager import installation
from backend_manager.installation import (
    InstallationConfigError,
    InstalledLayout,
    WindowsReleaseConfig,
    load_installed_release_config,
    parse_installed_layout,
    validate_installed_backend_stopped,
    validate_installed_service_contract,
)


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
    )


def test_parse_installed_layout_builds_program_data_paths(tmp_path: Path) -> None:
    layout = parse_installed_layout(
        {
            "InstallDir": str(tmp_path / "program"),
            "DataRoot": str(tmp_path / "data"),
            "BackendPort": "8001",
            "PgPort": "5440",
            "BackendServiceName": "TicketboxBackendCustom",
            "PgServiceName": "TicketboxPgCustom",
            "BackendVersion": "9.8.7-test",
        },
    )
    layout.release_config_path.parent.mkdir(parents=True)
    layout.release_config_path.write_text(
        json.dumps(
            {
                "schema": "ticketbox-windows-release-v1",
                "backend_service_name": "TicketboxBackendCustom",
                "pg_service_name": "TicketboxPgCustom",
                "service_state_timeout_ms": 17_000,
                "service_poll_interval_ms": 125,
                "postgres_ready_timeout_ms": 23_000,
                "backend_ready_timeout_ms": 31_000,
                "backend_ready_poll_interval_ms": 375,
                "backend_health_request_timeout_ms": 1_750,
            },
        ),
        encoding="utf-8",
    )
    release = load_installed_release_config(layout)

    assert layout.install_dir == (tmp_path / "program").resolve()
    assert layout.app_data_dir == (tmp_path / "data" / "app").resolve()
    assert layout.release_config_path == layout.install_dir / "installer" / "windows-release-config.json"
    assert layout.backend_port == 8001
    assert layout.pg_port == 5440
    assert layout.backend_service_name == "TicketboxBackendCustom"
    assert layout.pg_service_name == "TicketboxPgCustom"
    assert layout.backend_version == "9.8.7-test"
    assert layout.installation_id.startswith("ticketbox-")
    assert release.service_state_timeout_seconds == 17
    assert release.backend_ready_poll_seconds == 0.375


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DataRoot": ""}, "DataRoot"),
        ({"BackendPort": "abc"}, "BackendPort"),
        ({"PgPort": "70000"}, "PgPort"),
        ({"BackendServiceName": "bad/service"}, "BackendServiceName"),
    ],
)
def test_parse_installed_layout_rejects_incomplete_or_invalid_values(overrides, message: str) -> None:
    values = {
        "InstallDir": r"C:\Program Files\Ticketbox",
        "DataRoot": r"C:\ProgramData\Ticketbox",
        "BackendPort": "8000",
        "PgPort": "5432",
        "BackendServiceName": "TicketboxBackend",
        "PgServiceName": "TicketboxPg",
        "BackendVersion": "1.2.0",
    }
    values.update(overrides)

    with pytest.raises(InstallationConfigError, match=message):
        parse_installed_layout(values)


def test_service_contract_validator_uses_installed_script_and_dynamic_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "program"
    script = install_dir / "installer" / "install_bundled_services.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# contract", encoding="utf-8")
    powershell = tmp_path / "powershell.exe"
    powershell.write_bytes(b"MZ")
    layout = InstalledLayout(
        install_dir=install_dir,
        data_root=tmp_path / "data",
        backend_port=8123,
        pg_port=5544,
        backend_service_name="TicketboxBackendDynamic",
        pg_service_name="TicketboxPgDynamic",
        backend_version="9.8.7-test",
    )
    release = _release_config()
    release = WindowsReleaseConfig(
        **{
            **release.__dict__,
            "backend_service_name": "TicketboxBackendDynamic",
            "pg_service_name": "TicketboxPgDynamic",
        },
    )
    captured: list[list[str]] = []
    timeouts: list[float] = []

    monkeypatch.setattr(installation, "_windows_powershell_path", lambda: powershell)
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        lambda command, **kwargs: (
            captured.append(command),
            timeouts.append(kwargs["timeout"]),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        )[-1],
    )

    validate_installed_service_contract(layout, release)
    validate_installed_backend_stopped(layout, release)

    command = captured[0]
    assert command[0] == str(powershell)
    assert command[command.index("-ExpectedBackendServiceName") + 1] == "TicketboxBackendDynamic"
    assert command[command.index("-ExpectedPgServiceName") + 1] == "TicketboxPgDynamic"
    assert command[-1] == "-ValidateInstalledServicesOnly"
    assert captured[1][-1] == "-ValidateBackendRuntimeStoppedOnly"
    assert timeouts == [17, 17]
