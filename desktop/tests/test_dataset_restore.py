"""Installed complete-dataset restore UAC adapter contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend_manager import dataset_restore
from backend_manager.dataset_restore import run_installed_dataset_restore
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError

GENERATION = "ticketbox-backup-11111111-1111-4111-8111-111111111111"


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
    script = layout.install_dir / "installer" / "windows_dataset_restore.ps1"
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
    )
    return layout, release, powershell, script


def _result(**overrides: object) -> str:
    payload: dict[str, object] = {
        "schema": "ticketbox-complete-dataset-restore-result-v1",
        "backup_id": "11111111-1111-4111-8111-111111111111",
        "dataset_id": "22222222-2222-4222-8222-222222222222",
        "restore_epoch": 5,
        "generation_operation_id": "33333333-3333-4333-8333-333333333333",
        "result": "current_published",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")) + "\n"


def test_installed_restore_invokes_exact_owner_with_explicit_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, script = _subject(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=_result(), stderr="")

    monkeypatch.setattr(dataset_restore.subprocess, "run", run)
    run_installed_dataset_restore(layout, release, GENERATION)

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
        "-BackupGeneration",
        GENERATION,
    ]
    assert captured["cwd"] == script.parent
    assert captured["timeout"] == release.helper_watchdog_seconds("restore")
    assert "DATABASE_URL" not in captured["env"]


def test_installed_restore_rejects_result_for_another_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)
    monkeypatch.setattr(
        dataset_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=_result(backup_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            stderr="",
        ),
    )

    with pytest.raises(RuntimeControlError):
        run_installed_dataset_restore(layout, release, GENERATION)


@pytest.mark.parametrize(
    "generation",
    [
        "ticketbox-backup-latest",
        "../ticketbox-backup-11111111-1111-4111-8111-111111111111",
        "TICKETBOX-BACKUP-11111111-1111-4111-8111-111111111111",
    ],
)
def test_installed_restore_rejects_implicit_or_noncanonical_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    generation: str,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)
    with pytest.raises(RuntimeControlError, match="备份 generation"):
        run_installed_dataset_restore(layout, release, generation)
