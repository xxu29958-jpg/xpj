"""Installer registry parsing contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager.installation import InstallationConfigError, parse_installed_layout


def test_parse_installed_layout_builds_program_data_paths(tmp_path: Path) -> None:
    layout = parse_installed_layout(
        {
            "InstallDir": str(tmp_path / "program"),
            "DataRoot": str(tmp_path / "data"),
            "BackendPort": "8001",
            "PgPort": "5440",
        },
    )

    assert layout.install_dir == (tmp_path / "program").resolve()
    assert layout.app_data_dir == (tmp_path / "data" / "app").resolve()
    assert layout.env_path == layout.app_data_dir / ".env"
    assert layout.log_path == layout.app_data_dir / "logs" / "backend.log"
    assert layout.backend_port == 8001
    assert layout.pg_port == 5440


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DataRoot": ""}, "DataRoot"),
        ({"BackendPort": "abc"}, "BackendPort"),
        ({"PgPort": "70000"}, "PgPort"),
    ],
)
def test_parse_installed_layout_rejects_incomplete_or_invalid_values(overrides, message: str) -> None:
    values = {
        "InstallDir": r"C:\Program Files\Ticketbox",
        "DataRoot": r"C:\ProgramData\Ticketbox",
        "BackendPort": "8000",
        "PgPort": "5432",
    }
    values.update(overrides)

    with pytest.raises(InstallationConfigError, match=message):
        parse_installed_layout(values)
