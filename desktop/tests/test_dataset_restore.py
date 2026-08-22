"""Installed complete-dataset restore UAC adapter contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend_manager import dataset_restore
from backend_manager.dataset_restore import run_installed_dataset_restore
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError

GENERATION = "ticketbox-backup-11111111-1111-4111-8111-111111111111"
ATTEMPT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _trusted_system_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dataset_restore,
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
        dataset_backup_helper_timeout_ms=1_800_000,
        dataset_restore_helper_timeout_ms=3_600_000,
        dataset_payload_verification_timeout_ms=1_800_000,
        complete_dataset_backup_timeout_ms=5_400_000,
        complete_dataset_restore_timeout_ms=10_800_000,
    )
    return layout, release, powershell, script


def _result(**overrides: object) -> str:
    payload: dict[str, object] = {
        "schema": "ticketbox-complete-dataset-restore-result-v1",
        "restore_attempt_id": ATTEMPT_ID,
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
    outcome = run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)

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
        "-RestoreAttemptId",
        ATTEMPT_ID,
    ]
    assert captured["cwd"] == script.parent
    assert captured["timeout"] == release.powershell_action_timeout_seconds("restore")
    assert "DATABASE_URL" not in captured["env"]
    assert outcome == "current_published"


def test_installed_restore_ignores_ambient_executable_and_command_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    poison = tmp_path / "poison"
    monkeypatch.setenv("SYSTEMROOT", str(poison))
    monkeypatch.setenv("WINDIR", str(poison))
    monkeypatch.setenv("ComSpec", str(poison / "cmd.exe"))
    monkeypatch.setenv("PATH", str(poison))
    monkeypatch.setattr(dataset_restore, "windows_system_directory", lambda: powershell.parents[2])
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=_result(), stderr="")

    monkeypatch.setattr(dataset_restore.subprocess, "run", run)
    run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)

    assert captured["command"][0] == str(powershell)
    assert str(poison) not in "\n".join(captured["env"].values())


def test_restore_ui_preserves_unknown_result_truth() -> None:
    ui = (Path(__file__).resolve().parents[1] / "backend_manager" / "ui.html").read_text(encoding="utf-8")

    assert "完整恢复未完成；原数据仍被保留" not in ui
    assert "完整恢复结果未知；请刷新服务和数据状态后，重试同一 generation。" in ui


def test_installed_restore_reports_superseded_terminal_without_claiming_current_success(
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
            stdout=_result(result="superseded"),
            stderr="",
        ),
    )

    assert (
        run_installed_dataset_restore(
            layout,
            release,
            GENERATION,
            ATTEMPT_ID,
        )
        == "superseded"
    )


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
        run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)


def test_installed_restore_rejects_result_for_another_attempt(
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
            stdout=_result(restore_attempt_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            stderr="",
        ),
    )

    with pytest.raises(RuntimeControlError, match="结果未知"):
        run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)


def test_installed_restore_does_not_misreport_an_unconfirmed_result_as_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)
    monkeypatch.setattr(
        dataset_restore.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="suppressed"),
    )

    with pytest.raises(RuntimeControlError, match="结果未知"):
        run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)


@pytest.mark.parametrize(
    ("completed", "expected_cause"),
    [
        (SimpleNamespace(returncode=0, stdout="{", stderr=""), json.JSONDecodeError),
        (SimpleNamespace(returncode=0, stdout=_result() + _result(), stderr=""), None),
        (
            SimpleNamespace(
                returncode=0,
                stdout=_result(dataset_id="not-a-uuid"),
                stderr="",
            ),
            None,
        ),
    ],
)
def test_installed_restore_all_unconfirmed_results_use_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    completed: SimpleNamespace,
    expected_cause: type[BaseException] | None,
) -> None:
    layout, release, powershell, _script = _subject(tmp_path)
    monkeypatch.setenv("SYSTEMROOT", str(powershell.parents[3]))
    monkeypatch.setattr(dataset_restore, "require_local_fixed_regular_file", lambda path, *, label: path)
    monkeypatch.setattr(dataset_restore.subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(RuntimeControlError, match="结果未知") as raised:
        run_installed_dataset_restore(layout, release, GENERATION, ATTEMPT_ID)
    if expected_cause is not None:
        assert isinstance(raised.value.__cause__, expected_cause)


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
        run_installed_dataset_restore(layout, release, generation, ATTEMPT_ID)
