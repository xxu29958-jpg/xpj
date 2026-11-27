"""Core CLI, error-reporting, and Windows process-boundary tests for Rev3.2 §9.6–§9.8."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _uninstall_reinstall_fixtures import (
    DATASET_ID,
    _installed_fixture,
    _NoopMachineSecurity,
    _RecordingUninstallPlatform,
    _setup_from_installed_cli_env,
)
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.schemas import OPERATION_SCHEMA


def test_run_windows_process_raises_termination_unconfirmed_when_process_survives_kill_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from ticketbox_lifecycle.runtime import command as command_mod
    from ticketbox_lifecycle.runtime import windows_process

    class StuckProcess:
        pid = 99999
        stdin = None
        stdout = None
        stderr = None
        returncode = None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["pg_ctl.exe"], timeout or 1)

        def kill(self):
            return None

        def poll(self):
            return None

    class FakeJob:
        def assign(self, _pid: int) -> None:
            return None

        def terminate(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(windows_process.os, "name", "nt")
    monkeypatch.setattr(windows_process.subprocess, "Popen", lambda *a, **kw: StuckProcess())
    monkeypatch.setattr(windows_process, "_resume_suspended_process", lambda _pid: None)

    with pytest.raises(windows_process.ProcessTerminationUnconfirmedError):
        windows_process.run_windows_process(
            ["pg_ctl.exe", "start"],
            env={},
            timeout_s=1,
            input_text=None,
            job=cast(Any, FakeJob()),
            capture_output=False,
        )

    # Verify _SubprocessManagedJob.run_background_starter maps it to starter_process_not_exited!
    managed_job = command_mod._SubprocessManagedJob()
    managed_job._job = SimpleNamespace(
        run=lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("stuck")
        )
    )
    with pytest.raises(LifecycleError) as mapped_exc:
        managed_job.run_background_starter(["pg_ctl.exe", "start"], env={}, timeout_s=1)
    assert mapped_exc.value.code == "starter_process_not_exited"

    # Verify SubprocessCommandRunner.run ALSO maps ProcessTerminationUnconfirmedError to LifecycleError!
    monkeypatch.setattr(
        command_mod,
        "_run_process",
        lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("stuck stop")
        ),
    )
    with pytest.raises(LifecycleError) as run_mapped_exc:
        command_mod.SubprocessCommandRunner().run(["pg_ctl.exe", "stop"], env={}, timeout_s=1)
    assert run_mapped_exc.value.code == "command_termination_unconfirmed"


def test_purge_data_cli_reports_purge_probe_stop_failed_not_unhandled_on_dual_termination_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle import purge_data_cli
    from ticketbox_lifecycle.runtime import command as command_mod
    from ticketbox_lifecycle.runtime import windows_dataset, windows_process
    from ticketbox_lifecycle.runtime import windows_security_native as native

    req, stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    monkeypatch.setattr(native, "current_process_user_sid", lambda: None)

    class DualUnconfirmedRunner(command_mod.SubprocessCommandRunner):
        def open_managed_job(self):
            class StuckStarterJob:
                def __enter__(self_job):
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    del argv
                    raise LifecycleError("starter_process_not_exited", "pg_ctl start stuck")

                def __exit__(self_job, *_exc):
                    return None

            return StuckStarterJob()

        def run(self, argv, *, env=None, timeout_s=120, input_text=None):
            exe = Path(argv[0]).name.lower()
            if exe == "sc.exe":
                return CompletedCommand(tuple(argv), 1060, "", "missing")
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            return super().run(argv, env=env, timeout_s=timeout_s, input_text=input_text)

    # Make SubprocessCommandRunner.run -> _run_process raise ProcessTerminationUnconfirmedError on pg_ctl stop!
    monkeypatch.setattr(
        command_mod,
        "_run_process",
        lambda *a, **kw: (_ for _ in ()).throw(
            windows_process.ProcessTerminationUnconfirmedError("pg_ctl stop stuck")
        ),
    )

    dual_runner = DualUnconfirmedRunner()
    real_dataset = windows_dataset.WindowsDatasetAdapter(dual_runner, SimpleNamespace())
    setattr(stores, "_adapters", SimpleNamespace(dataset=real_dataset))

    result_file = tmp_path / "purge-dual-result.json"
    monkeypatch.setattr(purge_data_cli, "require_windows", lambda: None)
    monkeypatch.setattr(
        purge_data_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(purge_data_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(purge_data_cli, "ticketbox_program_data_root", lambda: program_data)
    monkeypatch.setattr(purge_data_cli.FilesystemStores, "from_installed", lambda **_kw: stores)
    monkeypatch.setattr(purge_data_cli, "SubprocessCommandRunner", lambda: dual_runner)

    rc = purge_data_cli.main([
        "purge-data",
        "--dataset-id",
        DATASET_ID,
        "--confirm-dataset-id",
        DATASET_ID,
        "--external-backups-status",
        "preserved_outside",
        "--confirm-permanent-delete",
        "--result",
        str(result_file),
    ])
    assert rc == 2
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "purge_probe_stop_failed"
    assert "starter_process_not_exited" in payload["message"]


def test_windows_managed_job_timeout_runs_on_timeout_before_killing_starter_or_closing_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes
    import os
    import socket
    import subprocess
    import sys
    import time
    from ctypes import wintypes

    if os.name != "nt":
        pytest.skip("Windows Job Object timeout ordering test requires Windows")

    from ticketbox_lifecycle.runtime import windows_process

    monkeypatch.setattr(windows_process, "_TERMINATION_TIMEOUT_S", 1)

    # Sub-case 1: Real starter exits cleanly when on_timeout signals stop -> process.kill() is NEVER needed!
    stop_flag = tmp_path / "stop.flag"
    cooperative_script = tmp_path / "coop_starter.py"
    cooperative_script.write_text(
        "import pathlib, sys, time\n"
        "flag = pathlib.Path(sys.argv[1])\n"
        "while not flag.exists():\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    events: list[str] = []
    orig_popen_kill = subprocess.Popen.kill
    orig_job_close = windows_process.PersistentKillOnCloseJob.close

    def tracked_kill(self):
        events.append("starter_kill")
        return orig_popen_kill(self)

    def tracked_close(self):
        events.append("job_close")
        return orig_job_close(self)

    monkeypatch.setattr(subprocess.Popen, "kill", tracked_kill)
    monkeypatch.setattr(windows_process.PersistentKillOnCloseJob, "close", tracked_close)

    def _signal_stop() -> None:
        events.append("on_timeout")
        stop_flag.write_text("stop", encoding="ascii")

    with pytest.raises(subprocess.TimeoutExpired):
        with windows_process.PersistentKillOnCloseJob() as job:
            job.run(
                [sys.executable, str(cooperative_script), str(stop_flag)],
                timeout_s=1,
                capture_output=False,
                on_timeout=_signal_stop,
            )
    assert events == ["on_timeout", "job_close"]

    # Sub-case 2: Stubborn starter + real grandchild daemon (modeling pg_ctl start + postgres.exe):
    # on_timeout gracefully shuts down the grandchild and waits on its Win32 process handle to prove
    # exit_code == 0 BEFORE starter_kill and job_close!
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    clean_exit_marker = tmp_path / "grandchild_clean_exit.txt"
    grandchild_pid_file = tmp_path / "grandchild.pid"
    grandchild_script = tmp_path / "grandchild_pg.py"
    grandchild_script.write_text(
        "import os, pathlib, socket, sys\n"
        "port = int(sys.argv[1])\n"
        "marker = pathlib.Path(sys.argv[2])\n"
        "pid_file = pathlib.Path(sys.argv[3])\n"
        "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', port))\n"
        "srv.listen(5)\n"
        "pid_file.write_text(str(os.getpid()), encoding='ascii')\n"
        "conn, _ = srv.accept()\n"
        "with conn:\n"
        "    cmd = conn.recv(16)\n"
        "    if cmd == b'FAST_STOP':\n"
        "        marker.write_text('clean_shutdown', encoding='ascii')\n"
        "        conn.sendall(b'STOPPED')\n"
        "srv.close()\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stubborn_starter = tmp_path / "stubborn_starter.py"
    stubborn_starter.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def _graceful_stop_grandchild() -> None:
        events.append("on_timeout_begin")
        deadline = time.monotonic() + 5.0
        while not grandchild_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        grandchild_pid = int(grandchild_pid_file.read_text(encoding="ascii").strip())
        proc_handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, grandchild_pid)
        assert proc_handle
        try:
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1.0) as client:
                        client.sendall(b"FAST_STOP")
                        assert client.recv(16) == b"STOPPED"
                        break
                except OSError:
                    time.sleep(0.05)
            assert clean_exit_marker.read_text(encoding="ascii") == "clean_shutdown"
            wait_res = kernel32.WaitForSingleObject(proc_handle, 5000)
            assert wait_res == 0
            exit_code = wintypes.DWORD(0xFFFFFFFF)
            assert kernel32.GetExitCodeProcess(proc_handle, ctypes.byref(exit_code))
            assert exit_code.value == 0
        finally:
            kernel32.CloseHandle(proc_handle)
        events.append("grandchild_clean_exit")

    events.clear()
    with pytest.raises(subprocess.TimeoutExpired):
        with windows_process.PersistentKillOnCloseJob() as job:
            job.run(
                [
                    sys.executable,
                    str(stubborn_starter),
                    str(grandchild_script),
                    str(port),
                    str(clean_exit_marker),
                    str(grandchild_pid_file),
                ],
                timeout_s=1,
                capture_output=False,
                on_timeout=_graceful_stop_grandchild,
            )
    assert events == ["on_timeout_begin", "grandchild_clean_exit", "starter_kill", "job_close"]


def test_windows_managed_job_keeps_grandchild_daemon_alive_across_starter_exit_and_kills_on_close(
    tmp_path: Path,
) -> None:
    import os
    import socket
    import sys
    import time

    if os.name != "nt":
        pytest.skip("Windows Job Object lifecycle test requires Windows")

    from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    pid_file = tmp_path / "daemon.pid"
    daemon_script = tmp_path / "daemon.py"
    starter_script = tmp_path / "starter.py"
    client_script = tmp_path / "client.py"

    daemon_script.write_text(
        "import pathlib, socket, sys\n"
        "port = int(sys.argv[1])\n"
        "pid_path = pathlib.Path(sys.argv[2])\n"
        "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', port))\n"
        "srv.listen(5)\n"
        "pid_path.write_text(str(__import__('os').getpid()), encoding='ascii')\n"
        "while True:\n"
        "    conn, _ = srv.accept()\n"
        "    with conn:\n"
        "        conn.sendall(b'DATASET_OK\\n')\n",
        encoding="utf-8",
    )
    starter_script.write_text(
        "import socket, subprocess, sys, time\n"
        "port = int(sys.argv[1])\n"
        "proc = subprocess.Popen([sys.executable, sys.argv[2], str(port), sys.argv[3]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "deadline = time.monotonic() + 10\n"
        "while time.monotonic() < deadline:\n"
        "    try:\n"
        "        with socket.create_connection(('127.0.0.1', port), timeout=0.5):\n"
        "            sys.exit(0)\n"
        "    except OSError:\n"
        "        time.sleep(0.05)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    client_script.write_text(
        "import socket, sys\n"
        "with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=5) as c:\n"
        "    print(c.recv(64).decode('ascii').strip())\n",
        encoding="utf-8",
    )

    runner = SubprocessCommandRunner()
    with runner.open_managed_job() as job:
        started = job.run_background_starter(
            [sys.executable, str(starter_script), str(port), str(daemon_script), str(pid_file)],
            timeout_s=20,
        )
        assert started.returncode == 0
        # Starter process has already exited, yet grandchild daemon MUST remain alive for a separate runner.run call!
        queried = runner.run([sys.executable, str(client_script), str(port)], timeout_s=15)
        assert queried.returncode == 0
        assert queried.stdout.strip() == "DATASET_OK"

    # Exiting the managed job context MUST terminate the grandchild via JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE!
    deadline = time.monotonic() + 5.0
    stopped = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                time.sleep(0.05)
        except OSError:
            stopped = True
            break
    assert stopped is True


def test_uninstall_cli_check_preflight_single_authority_admission_and_zero_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle import cli, uninstall_cli
    from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
    from ticketbox_lifecycle.schemas import UninstallOperation

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    program_data = tmp_path / "中文路径" / "Ticketbox"
    machine_root = program_data / "machine"
    machine_root.mkdir(parents=True)
    chinese_data_root = str(program_data / "data")

    _, _mem, _adapters, base_binding = _installed_fixture(tmp_path)
    binding = replace(base_binding, data_root=chinese_data_root)
    op_id = f"uninstall-{binding.release_manifest_sha256}"

    class PoisonMutex:
        def acquire(self) -> None:
            raise AssertionError("read-only --check-preflight must never acquire lifecycle mutex")

        def release(self) -> None:
            raise AssertionError("read-only --check-preflight must never release lifecycle mutex")

    def _from_installed(*, install_root: Path | None = None, program_data_root: Path | None = None) -> FilesystemStores:
        resolved_pd = program_data_root if program_data_root is not None else program_data
        return FilesystemStores(
            resolved_pd / "machine",
            binding.backend_service_name,
            SimpleNamespace(security=_NoopMachineSecurity()),
            PoisonMutex(),
            install_root=install_root,
            program_data_root=resolved_pd,
        )

    monkeypatch.setattr(uninstall_cli, "require_windows", lambda: None)
    monkeypatch.setattr(uninstall_cli, "ticketbox_install_root", lambda: app_dir)
    monkeypatch.setattr(uninstall_cli, "ticketbox_program_data_root", lambda: program_data)
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    monkeypatch.setattr(uninstall_cli.FilesystemStores, "from_installed", staticmethod(_from_installed))

    def _snapshot(root: Path) -> list[tuple[str, bool, bytes | None]]:
        entries: list[tuple[str, bool, bytes | None]] = []
        for item in sorted(root.rglob("*")):
            rel = str(item.relative_to(root))
            entries.append((rel, item.is_dir(), item.read_bytes() if item.is_file() else None))
        return entries

    binding_path = machine_root / "installation.json"
    active_path = machine_root / "operations" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Missing installation.json -> refused (exit 2), zero disk writes.
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "uninstall_binding_missing" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # Write valid installation.json with Chinese data_root serialized as \uXXXX by json.dump(..., ensure_ascii=True).
    binding_raw = json.dumps(asdict(binding), indent=2, sort_keys=True) + "\n"
    assert r"\u" in binding_raw
    binding_path.write_text(binding_raw, encoding="utf-8")

    # 2. Absent active.json + valid installation.json -> allowed (exit 0) via both uninstall_cli and cli.main.
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0
    assert cli.main(["uninstall", "--check-preflight"]) == 0
    assert _snapshot(tmp_path) == before

    # 3. Valid failed_recoverable uninstall record with Chinese data_root (\uXXXX) -> allowed (exit 0)!
    from ticketbox_lifecycle.domain.uninstall import _uninstall_request_hash

    valid_active = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=op_id,
        kind="uninstall",
        request_hash=_uninstall_request_hash(binding),
        target_release_id=binding.active_release_id,
        data_root=chinese_data_root,
        release_manifest_sha256=binding.release_manifest_sha256,
        backend_port=binding.backend_port,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="unregister_services",
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key=binding.health_attestation_key,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    active_dict = asdict(valid_active)
    valid_active_raw = json.dumps(active_dict, indent=2, sort_keys=True) + "\n"
    assert r"\u" in valid_active_raw
    active_path.write_text(valid_active_raw, encoding="utf-8")
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0
    assert _snapshot(tmp_path) == before

    # 4. Nested object containing "phase": "failed_recoverable" while top-level lacks "phase" -> refused (exit 2)!
    nested_missing_top_phase = dict(active_dict)
    del nested_missing_top_phase["phase"]
    nested_missing_top_phase["nested"] = {"phase": "failed_recoverable"}
    active_path.write_text(json.dumps(nested_missing_top_phase, indent=2, sort_keys=True), encoding="utf-8")
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "bad_operation_fields" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # 5. Duplicate "phase" key and unicode-escaped duplicate key -> refused (exit 2)!
    compact_valid = json.dumps(active_dict, sort_keys=True)
    for tampered in (
        compact_valid[:-1] + ', "phase": "prepared"}',
        compact_valid[:-1] + r', "phas\u0065": "prepared"}',
    ):
        active_path.write_text(tampered, encoding="utf-8")
        before = _snapshot(tmp_path)
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        assert "machine_state_invalid" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    # 6. Non-recoverable phase, invalid/mismatched manifest digest, or wrong operation_id -> refused (exit 2)!
    for bad_overrides in (
        {"phase": "prepared"},
        {"release_manifest_sha256": "not-hex"},
        {"release_manifest_sha256": "z" * 64},
        {"release_manifest_sha256": "e" * 64},
        {"operation_id": "uninstall-other"},
    ):
        bad_payload = {**active_dict, **bad_overrides}
        active_path.write_text(json.dumps(bad_payload, indent=2, sort_keys=True), encoding="utf-8")
        before = _snapshot(tmp_path)
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        assert "uninstall_operation_active" in capsys.readouterr().err
        assert _snapshot(tmp_path) == before

    # 7. Directory occupying active.json -> refused (exit 2), zero disk writes!
    active_path.unlink()
    active_path.mkdir()
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "machine_state_invalid" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before
    active_path.rmdir()

    # 8. Non-admin caller -> refused (exit 2) with zero disk writes!
    active_path.write_text(valid_active_raw, encoding="utf-8")
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 0)),
        raising=False,
    )
    before = _snapshot(tmp_path)
    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
    assert "uninstall_admin_required" in capsys.readouterr().err
    assert _snapshot(tmp_path) == before

    # 9. Explicit empty/incompatible flags with --check-preflight MUST be rejected (exit 2) with zero disk writes!
    monkeypatch.setattr(
        uninstall_cli.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1)),
        raising=False,
    )
    for bad_argv in (
        ["uninstall", "--check-preflight", "--result="],
        ["uninstall", "--check-preflight", "--request="],
        ["uninstall", "--check-preflight", "--from-installed"],
    ):
        before = _snapshot(tmp_path)
        with pytest.raises(SystemExit) as arg_exc:
            uninstall_cli.main(bad_argv)
        assert arg_exc.value.code == 2
        capsys.readouterr()
        assert _snapshot(tmp_path) == before


def test_uninstall_cli_from_installed_single_authority_flow_and_forbidden_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import asdict

    from ticketbox_lifecycle.schemas import UninstallOperation

    env = _setup_from_installed_cli_env(tmp_path, monkeypatch)
    uninstall_cli = env.uninstall_cli
    binding = env.binding

    escaped_key_binding = env.binding_raw.replace('"active_release_id"', r'"active_releas\u0065_id"', 1)
    assert r'"active_releas\u0065_id"' in escaped_key_binding
    assert r"\u" in env.binding_raw
    env.binding_path.write_text(escaped_key_binding, encoding="utf-8")
    from ticketbox_lifecycle.domain.uninstall import _uninstall_request_hash

    active_op = UninstallOperation(
        schema=OPERATION_SCHEMA,
        operation_id=env.expected_op_id,
        kind="uninstall",
        request_hash=_uninstall_request_hash(binding),
        target_release_id=binding.active_release_id,
        data_root=env.chinese_data_root,
        release_manifest_sha256=env.manifest_sha,
        backend_port=binding.backend_port,
        phase="failed_recoverable",
        no_return_point=True,
        completed_step="unregister_services",
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
        schema_revision="20261101_0001",
        health_attestation_key=binding.health_attestation_key,
        expected_restore_epoch=binding.expected_restore_epoch,
    )
    env.active_path.write_text(json.dumps(asdict(active_op), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 0
    env.root_calls["install"] = 0
    env.root_calls["program_data"] = 0
    safe_result = tmp_path / "private-result" / "uninstall-result.json"
    safe_result.parent.mkdir(parents=True)
    assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(safe_result)]) == 0
    assert env.root_calls == {"install": 1, "program_data": 1}
    assert env.platform_box[0].unregister_called is True
    assert env.platform_box[0].cleanup_called is True
    assert len(env.platform_box[0].requests) == 1
    req0 = env.platform_box[0].requests[0]
    assert req0.operation_id == env.expected_op_id
    assert req0.target_release_id == binding.active_release_id
    assert req0.release_manifest_sha256 == env.manifest_sha
    assert req0.install_id == binding.install_id
    assert req0.dataset_id == binding.dataset_id
    assert not env.active_path.exists()
    assert (env.machine_root / "operations" / "history" / f"{env.expected_op_id}.json").is_file()
    result_payload = json.loads(safe_result.read_text(encoding="utf-8"))
    assert result_payload["ok"] is True
    assert result_payload["phase"] == "committed"
    assert result_payload["operation_id"] == env.expected_op_id
    assert result_payload["code"] == "uninstalled_data_preserved"

    env.binding_path.write_text(env.binding_raw, encoding="utf-8")
    assert not env.active_path.exists()
    upgraded_binding = replace(
        binding,
        active_release_id="1.4.0",
        previous_release_id=binding.active_release_id,
        release_manifest_sha256="b" * 64,
    )
    env.platform_box[0] = _RecordingUninstallPlatform(binding.active_release_id)
    env.mutex_on_acquire.append(
        lambda: env.binding_path.write_text(
            json.dumps(asdict(upgraded_binding), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    )
    race_result = tmp_path / "private-result" / "race-result.json"
    assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(race_result)]) == 2
    assert "uninstall_identity_mismatch" in capsys.readouterr().err
    assert env.platform_box[0].verify_called is False
    assert env.platform_box[0].unregister_called is False
    assert not env.active_path.exists()
    race_payload = json.loads(race_result.read_text(encoding="utf-8"))
    assert race_payload["ok"] is False
    assert race_payload["code"] == "uninstall_identity_mismatch"


def test_uninstall_cli_from_installed_rejects_bad_binding_and_forbidden_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import asdict

    env = _setup_from_installed_cli_env(tmp_path, monkeypatch)
    uninstall_cli = env.uninstall_cli
    binding = env.binding
    safe_result = tmp_path / "private-result" / "uninstall-result.json"
    safe_result.parent.mkdir(parents=True)

    compact_binding = json.dumps(asdict(binding), sort_keys=True)
    for bad_binding_text in (
        compact_binding[:-1] + ', "data_root": "C:/evil/data"}',
        compact_binding[:-1] + "]",
    ):
        env.binding_path.write_text(bad_binding_text, encoding="utf-8")
        assert uninstall_cli.main(["uninstall", "--check-preflight"]) == 2
        capsys.readouterr()
        err_result = tmp_path / "private-result" / "bad-binding-result.json"
        if err_result.exists():
            err_result.unlink()
        assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(err_result)]) == 2
        capsys.readouterr()
        assert env.platform_box[0].verify_called is False
        assert env.platform_box[0].unregister_called is False
        assert json.loads(err_result.read_text(encoding="utf-8"))["ok"] is False

    env.binding_path.write_text(env.binding_raw, encoding="utf-8")
    env.platform_box[0] = _RecordingUninstallPlatform(binding.active_release_id)
    for evil_result in (env.app_dir / "evil.json", env.program_data / "evil.json"):
        assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(evil_result)]) == 2
        assert "unsafe_result_path" in capsys.readouterr().err
        assert not evil_result.exists()
        assert env.platform_box[0].verify_called is False
        assert env.platform_box[0].unregister_called is False

    external_data_root = tmp_path / "external-binding-data"
    external_data_root.mkdir(parents=True)
    bad_digest_external_binding = replace(
        binding,
        data_root=str(external_data_root),
        release_manifest_sha256="not-a-valid-sha256",
    )
    env.binding_path.write_text(
        json.dumps(asdict(bad_digest_external_binding), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evil_external_result = external_data_root / "evil-failure.json"
    assert uninstall_cli.main(["uninstall", "--from-installed", "--result", str(evil_external_result)]) == 2
    assert "unsafe_result_path" in capsys.readouterr().err
    assert not evil_external_result.exists()
    assert list(external_data_root.iterdir()) == []

    for bad_argv in (
        ["uninstall", "--from-installed"],
        ["uninstall", "--from-installed", "--result="],
        ["uninstall", "--from-installed", "--request=", "--result", str(safe_result)],
    ):
        with pytest.raises(SystemExit) as arg_exc:
            uninstall_cli.main(bad_argv)
        assert arg_exc.value.code == 2
        capsys.readouterr()
