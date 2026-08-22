"""Closed contract for the elevated, sanitized backup inventory projection."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend_manager import dataset_inventory
from backend_manager.dataset_inventory import decode_public_inventory, read_installed_dataset_inventory
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError


def _item() -> dict[str, object]:
    return {
        "generation": "ticketbox-backup-11111111-1111-4111-8111-111111111111",
        "dataset_id": "22222222-2222-4222-8222-222222222222",
        "restore_epoch": 3,
        "size_bytes": 4096,
        "created_at": "2026-08-23T10:11:12.123456Z",
    }


def _release() -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name="ticketbox-backend",
        pg_service_name="ticketbox-pg",
        service_state_timeout_ms=1_000,
        service_poll_interval_ms=20,
        postgres_ready_timeout_ms=1_000,
        backend_ready_timeout_ms=1_000,
        backend_ready_poll_interval_ms=20,
        backend_health_request_timeout_ms=100,
        database_tool_timeout_ms=5_000,
        complete_dataset_backup_timeout_ms=15_000,
        complete_dataset_restore_timeout_ms=30_000,
    )


def test_public_inventory_decoder_is_closed_and_canonical() -> None:
    assert decode_public_inventory([_item()])[0].public_projection() == _item()
    for mutation in (
        {**_item(), "payload_path": "C:/secret/database.dump"},
        {**_item(), "restore_epoch": True},
        {**_item(), "created_at": "2026-02-30T10:11:12.123456Z"},
    ):
        with pytest.raises(RuntimeControlError, match="条目"):
            decode_public_inventory([mutation])


def test_installed_inventory_uses_exact_system_powershell_and_sanitizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dir = tmp_path / "install"
    script = install_dir / "installer" / "windows_dataset_inventory.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# frozen test fixture", encoding="utf-8")
    layout = InstalledLayout(
        install_dir=install_dir,
        data_root=tmp_path / "data",
        backend_port=8123,
        pg_port=5432,
        backend_service_name="ticketbox-backend",
        pg_service_name="ticketbox-pg",
        backend_version="1.0.0",
    )
    system = tmp_path / "Windows" / "System32"
    powershell = system / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(dataset_inventory, "windows_system_directory", lambda: system)
    monkeypatch.setattr(
        dataset_inventory,
        "require_local_fixed_regular_file",
        lambda path, *, label: path,
    )
    monkeypatch.setattr(
        dataset_inventory,
        "trusted_windows_command_environment",
        lambda _system: {"SystemRoot": str(system.parent)},
    )

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        payload = {
            "schema": "ticketbox-manager-backup-inventory-v1",
            "generations": [{**_item(), "backup_id": "11111111-1111-4111-8111-111111111111", "kind": "manual"}],
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(dataset_inventory.subprocess, "run", run)
    assert read_installed_dataset_inventory(layout, _release())[0].public_projection() == _item()
    command, kwargs = calls[0]
    assert command[0] == str(powershell)
    assert command[command.index("-File") + 1] == str(script)
    assert command[command.index("-DataRoot") + 1] == str(layout.data_root)
    assert kwargs["cwd"] == script.parent
    assert kwargs["stdin"] is subprocess.DEVNULL
