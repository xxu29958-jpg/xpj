"""Source backend process ownership and failure normalization."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend_manager import process
from backend_manager.runtime import RuntimeControlError, SourceBackendRuntime


def test_source_runtime_normalizes_os_start_failure() -> None:
    class BrokenSupervisor:
        def start(self) -> None:
            raise OSError("access denied")

    runtime = SourceBackendRuntime(BrokenSupervisor())  # type: ignore[arg-type]

    with pytest.raises(RuntimeControlError, match="access denied"):
        runtime.start()


def test_source_spawn_overrides_extra_loopback_hosts_with_exact_custom_port(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakePopen:
        pid = 1234
        stdout = None

        def poll(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakePopen()

    monkeypatch.setenv(
        "XPJ_EXTRA_LOOPBACK_HOSTS",
        "0.0.0.0:9123,api.example.com,127.0.0.1:8000",
    )
    monkeypatch.setattr(process.subprocess, "Popen", fake_popen)
    events: list[str] = []

    class FakeJob:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        process,
        "_attach_kill_on_close_job",
        lambda _popen: (events.append("attach"), FakeJob())[-1],
    )
    monkeypatch.setattr(
        process,
        "_resume_suspended_process",
        lambda process_id: events.append(f"resume:{process_id}"),
    )

    process.spawn_backend(
        backend_root=tmp_path,
        venv_python=tmp_path / "python.exe",
        data_root=tmp_path / "runtime-data",
        host="127.0.0.1",
        port=9123,
    )

    child_environment = captured["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["XPJ_EXTRA_LOOPBACK_HOSTS"] == "127.0.0.1:9123"
    assert child_environment["TICKETBOX_DATA_DIR"] == str(tmp_path / "runtime-data")
    assert "api.example.com" not in child_environment["XPJ_EXTRA_LOOPBACK_HOSTS"]
    assert events == ["attach", "resume:1234"]
    assert int(captured["creationflags"]) & process._CREATE_SUSPENDED  # noqa: SLF001


def test_spawn_failure_to_attach_job_terminates_new_child(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []

    class FakePopen:
        pid = 1234
        stdout = None

        def kill(self) -> None:
            events.append("kill")

        def wait(self, timeout: float) -> int:
            events.append(f"wait:{timeout:g}")
            return 1

    monkeypatch.setattr(process.subprocess, "Popen", lambda *_args, **_kwargs: FakePopen())
    monkeypatch.setattr(
        process,
        "_attach_kill_on_close_job",
        lambda _popen: (_ for _ in ()).throw(OSError("job unavailable")),
    )

    with pytest.raises(OSError, match="job unavailable"):
        process.spawn_backend(
            backend_root=tmp_path,
            venv_python=tmp_path / "python.exe",
            data_root=tmp_path / "runtime-data",
            host="127.0.0.1",
            port=9123,
        )

    assert events == ["kill", "wait:5"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object required")
def test_suspended_job_launch_terminates_owned_child() -> None:
    child, job = process.spawn_windows_job_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        job.close()
        child.wait(timeout=5)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
