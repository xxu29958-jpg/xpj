"""Installed complete-dataset backup UAC adapter contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend_manager import dataset_backup
from backend_manager.dataset_backup import run_installed_dataset_backup
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError


@pytest.fixture(autouse=True)
def _trusted_system_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dataset_backup,
        "windows_system_directory",
        lambda: Path(os.environ["SYSTEMROOT"]) / "System32",
    )


def _subject(tmp_path: Path) -> tuple[InstalledLayout, WindowsReleaseConfig, Path, Path]:
    layout = InstalledLayout(
        install_dir=tmp_path / "program",
        data_root=tmp_path / "data",
        backend_port=8000,
        pg_port=5432,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        backend_version="1.2.3",
    )
    script = layout.install_dir / "installer" / "windows_dataset_backup.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# owner", encoding="utf-8")
    powershell = tmp_path / "Windows" / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    powershell.parent.mkdir(parents=True)
    powershell.write_bytes(b"MZ")
    release = WindowsReleaseConfig(
        backend_service_name=layout.backend_service_name,
        pg_service_name=layout.pg_service_name,
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
        complete_dataset_backup_timeout_ms=5_400_000,
        complete_dataset_restore_timeout_ms=10_800_000,
    )
    return layout, release, powershell, script


def _result(**overrides: object) -> str:
    backup_id = "11111111-1111-4111-8111-111111111111"
    payload: dict[str, object] = {
        "schema": "ticketbox-complete-dataset-backup-result-v1",
        "backup_id": backup_id,
        "generation": f"ticketbox-backup-{backup_id}",
        "dataset_id": "22222222-2222-4222-8222-222222222222",
        "restore_epoch": 4,
        "size_bytes": 1024,
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")) + "\n"


def test_installed_backup_invokes_exact_owner_with_closed_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, script = _subject(tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_backup, "require_local_fixed_regular_file", lambda path, *, label: path)

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=_result(), stderr="")

    monkeypatch.setattr(dataset_backup.subprocess, "run", run)

    run_installed_dataset_backup(layout, release)

    assert captured["command"] == [
        str(powershell),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-DataRoot",
        str(layout.data_root),
        "-BackupKind",
        "manual",
    ]
    assert captured["cwd"] == script.parent
    assert captured["timeout"] == release.powershell_action_timeout_seconds("backup")
    assert "DATABASE_URL" not in captured["env"]


def test_installed_backup_ignores_ambient_executable_and_command_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    poison = tmp_path / "poison"
    monkeypatch.setenv("SYSTEMROOT", str(poison))
    monkeypatch.setenv("WINDIR", str(poison))
    monkeypatch.setenv("ComSpec", str(poison / "cmd.exe"))
    monkeypatch.setenv("PATH", str(poison))
    monkeypatch.setattr(dataset_backup, "windows_system_directory", lambda: powershell.parents[2])
    monkeypatch.setattr(dataset_backup, "require_local_fixed_regular_file", lambda path, *, label: path)
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=_result(), stderr="")

    monkeypatch.setattr(dataset_backup.subprocess, "run", run)
    run_installed_dataset_backup(layout, release)

    assert captured["command"][0] == str(powershell)
    assert str(poison) not in "\n".join(captured["env"].values())


@pytest.mark.parametrize(
    "stdout",
    [
        _result(backup_id="not-a-uuid", generation="ticketbox-backup-not-a-uuid"),
        _result(dataset_id="NOT-CANONICAL"),
        _result(restore_epoch=True),
        _result(size_bytes=True),
        _result() + _result(),
    ],
)
def test_installed_backup_rejects_open_or_noncanonical_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: str,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_backup, "require_local_fixed_regular_file", lambda path, *, label: path)
    monkeypatch.setattr(
        dataset_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    with pytest.raises(RuntimeControlError, match="结果"):
        run_installed_dataset_backup(layout, release)
