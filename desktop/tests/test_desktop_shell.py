"""Desktop shell browser and Edge app-window behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_manager import desktop_shell


def test_edge_discovery_uses_only_validated_machine_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"test")
    monkeypatch.setattr(desktop_shell, "_registered_edge_candidates", lambda: (edge,))

    assert desktop_shell.discover_edge_executable() == str(edge.resolve())


def test_edge_discovery_rejects_untrusted_registered_candidate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"test")
    monkeypatch.setattr(desktop_shell, "_registered_edge_candidates", lambda: (edge,))
    monkeypatch.setattr(
        desktop_shell,
        "require_local_fixed_regular_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(desktop_shell.RuntimeControlError("untrusted")),
    )

    assert desktop_shell.discover_edge_executable() is None


def test_app_window_requires_a_waitable_edge_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop_shell, "discover_edge_executable", lambda: None)
    monkeypatch.setattr(
        desktop_shell,
        "open_in_browser",
        lambda url: (opened.append(url), True)[-1],
    )

    assert (
        desktop_shell.open_app_window(
            "http://127.0.0.1:8799/",
            profile=tmp_path / "profile",
        )
        is None
    )

    assert opened == []


def test_app_window_uses_a_dedicated_profile_and_returns_process_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class Process:
        def poll(self):
            return None

    class Job:
        def close(self) -> None:
            pass

    def spawn(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Process(), Job()

    monkeypatch.setattr(desktop_shell, "discover_edge_executable", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(desktop_shell, "spawn_windows_job_process", spawn)

    profile = tmp_path / "profile"
    window = desktop_shell.open_app_window("http://127.0.0.1:8799/", profile=profile)

    assert window is not None
    assert window.process.__class__ is Process
    assert f"--user-data-dir={profile.resolve()}" in captured["command"]
    assert "--edge-skip-compat-layer-relaunch" in captured["command"]
    assert "--disable-background-mode" in captured["command"]
    assert "--app=http://127.0.0.1:8799/" in captured["command"]
    assert captured["stdout"] is desktop_shell.subprocess.DEVNULL
    assert captured["stderr"] is desktop_shell.subprocess.DEVNULL


def test_edge_window_close_escalates_and_reports_process_exit() -> None:
    events: list[str] = []

    class Process:
        running = True

        def poll(self):
            return None if self.running else 0

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")
            self.running = False

        def wait(self, *, timeout: float):
            events.append(f"wait:{timeout:g}")
            if self.running:
                raise desktop_shell.subprocess.TimeoutExpired("edge", timeout)
            return 0

    window = desktop_shell.EdgeAppWindow(Process())

    assert window.close(timeout=1) is True
    assert events == ["terminate", "wait:1", "kill", "wait:1"]


def test_edge_window_closes_owned_job_before_waiting() -> None:
    events: list[str] = []

    class Process:
        def poll(self):
            return None

        def wait(self, *, timeout: float):
            events.append(f"wait:{timeout:g}")
            return 0

    class Job:
        def close(self) -> None:
            events.append("job-close")

    window = desktop_shell.EdgeAppWindow(Process(), Job())  # type: ignore[arg-type]

    assert window.close(timeout=1) is True
    assert events == ["job-close", "wait:1"]


def test_edge_window_tracks_visible_job_window_instead_of_lingering_process() -> None:
    events: list[str] = []

    class Process:
        def poll(self):
            return None

        def wait(self, *, timeout: float):
            events.append(f"wait:{timeout:g}")
            return 0

    class Job:
        visible = iter((False, True, False))

        def has_visible_top_level_window(self) -> bool:
            return next(self.visible)

        def close(self) -> None:
            events.append("job-close")

    window = desktop_shell.EdgeAppWindow(Process(), Job())  # type: ignore[arg-type]

    assert window.is_open() is True
    assert window.is_open() is True
    assert window.is_open() is False
    assert events == ["job-close", "wait:0.5"]


def test_edge_window_visibility_query_failure_is_bounded() -> None:
    events: list[str] = []

    class Process:
        def poll(self):
            return None

        def wait(self, *, timeout: float):
            events.append(f"wait:{timeout:g}")
            return 0

    class Job:
        def has_visible_top_level_window(self) -> bool:
            raise OSError("synthetic window query failure")

        def close(self) -> None:
            events.append("job-close")

    window = desktop_shell.EdgeAppWindow(Process(), Job())  # type: ignore[arg-type]

    assert window.is_open() is True
    assert window.is_open() is True
    assert window.is_open() is False
    assert window.is_open() is False
    assert events == ["job-close", "wait:0.5"]


def test_browser_launch_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        desktop_shell.os,
        "startfile",
        lambda *_args: (_ for _ in ()).throw(OSError("no association")),
        raising=False,
    )

    assert desktop_shell.open_in_browser("http://127.0.0.1:8799/") is False


def test_browser_launch_uses_windows_shell_without_command_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(desktop_shell.os, "startfile", opened.append, raising=False)

    assert desktop_shell.open_in_browser("http://127.0.0.1:8799/?a=1&b=2") is True
    assert opened == ["http://127.0.0.1:8799/?a=1&b=2"]
