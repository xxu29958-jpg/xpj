"""Desktop shell browser and Edge app-window behavior."""

from __future__ import annotations

import os
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

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(desktop_shell, "discover_edge_executable", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", popen)

    profile = tmp_path / "profile"
    bootstrap_url = (tmp_path / "bootstrap.html").as_uri()
    instance_secret = "instance-proof-secret-must-not-reach-edge"
    window = desktop_shell.open_app_window(bootstrap_url, profile=profile)

    assert window is not None
    assert window.process.__class__ is Process
    assert f"--user-data-dir={profile.resolve()}" in captured["command"]
    assert "--edge-skip-compat-layer-relaunch" in captured["command"]
    assert "--disable-background-mode" in captured["command"]
    assert f"--app={bootstrap_url}" in captured["command"]
    assert "--start-maximized" in captured["command"]
    assert instance_secret not in " ".join(captured["command"])
    assert instance_secret not in str(profile)
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


_TEST_IDENTITY = desktop_shell.ShellIdentity(
    app_id=desktop_shell.MANAGER_APP_ID,
    relaunch_command=r'"C:\Ticketbox\manager\ticketbox-manager.exe"',
    relaunch_icon=r"C:\Ticketbox\manager\ticketbox-manager.exe,0",
    display_name=desktop_shell.MANAGER_DISPLAY_NAME,
)


class _RunningProcess:
    pid = 4242

    def poll(self):
        return None


def test_manager_shell_identity_is_offered_only_by_the_installed_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(desktop_shell.sys, "frozen", raising=False)
    assert desktop_shell.manager_shell_identity() is None

    monkeypatch.setattr(desktop_shell.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_shell.sys, "executable", r"C:\Ticketbox\manager\ticketbox-manager.exe")
    identity = desktop_shell.manager_shell_identity()

    assert identity is not None
    assert identity.app_id == "Ticketbox.Manager"
    assert identity.relaunch_command.startswith('"') and identity.relaunch_command.endswith('ticketbox-manager.exe"')
    assert identity.relaunch_icon.endswith("ticketbox-manager.exe,0")
    assert identity.display_name == "管理小票夹"


def test_installer_shortcut_carries_the_manager_app_id() -> None:
    iss = Path(__file__).resolve().parents[2] / "distribution" / "windows" / "installer" / "ticketbox.iss"
    shortcut = next(line for line in iss.read_text(encoding="utf-8").splitlines() if "ticketbox-manager.exe" in line
                    and line.startswith("Name:"))

    assert f'AppUserModelID: "{desktop_shell.MANAGER_APP_ID}"' in shortcut


def test_app_window_receives_the_manager_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(desktop_shell, "discover_edge_executable", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(desktop_shell.subprocess, "Popen", lambda *_args, **_kwargs: _RunningProcess())
    monkeypatch.setattr(desktop_shell, "manager_shell_identity", lambda: _TEST_IDENTITY)

    window = desktop_shell.open_app_window("http://127.0.0.1:8799/", profile=tmp_path / "profile")

    assert window is not None
    assert window.identity is _TEST_IDENTITY


def test_each_visible_window_is_stamped_once(monkeypatch: pytest.MonkeyPatch) -> None:
    stamped: list[int] = []
    frames = iter([[], [101], [101, 202], [101, 202]])
    monkeypatch.setattr(desktop_shell, "_visible_windows", lambda _pid: next(frames))
    monkeypatch.setattr(desktop_shell, "_apply_shell_identity", lambda handle, identity: stamped.append(handle))
    window = desktop_shell.EdgeAppWindow(_RunningProcess(), identity=_TEST_IDENTITY)

    assert [window.is_open() for _ in range(4)] == [True, True, True, True]
    assert stamped == [101, 202]


def test_identity_failure_keeps_the_window_open_and_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def refuse(handle: int, _identity: object) -> None:
        attempts.append(handle)
        raise OSError("property store unavailable")

    monkeypatch.setattr(desktop_shell, "_visible_windows", lambda _pid: [101])
    monkeypatch.setattr(desktop_shell, "_apply_shell_identity", refuse)
    window = desktop_shell.EdgeAppWindow(_RunningProcess(), identity=_TEST_IDENTITY)

    assert window.is_open() is True
    assert window.is_open() is True
    assert attempts == [101]


def test_source_runs_leave_edge_windows_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop_shell, "_visible_windows", lambda _pid: [101])
    monkeypatch.setattr(
        desktop_shell,
        "_apply_shell_identity",
        lambda *_args: pytest.fail("a source run has no executable to relaunch"),
    )

    assert desktop_shell.EdgeAppWindow(_RunningProcess()).is_open() is True


_windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows shell property store")


def _read_identity(handle: int) -> tuple[str | None, str | None, str | None, str | None]:
    with desktop_shell._window_property_store(handle) as (read, _write):
        return read(5), read(2), read(3), read(4)


@_windows_only
def test_shell_identity_round_trips_on_a_real_window() -> None:
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    user32.DestroyWindow.argtypes = (ctypes.c_void_p,)
    handle = user32.CreateWindowExW(0, "STATIC", "ticketbox identity probe", 0x00CF0000, 0, 0, 120, 80,
                                    None, None, None, None)
    assert handle, ctypes.WinError(ctypes.get_last_error())
    try:
        desktop_shell._apply_shell_identity(handle, _TEST_IDENTITY)

        assert _read_identity(handle) == (
            _TEST_IDENTITY.app_id,
            _TEST_IDENTITY.relaunch_command,
            _TEST_IDENTITY.relaunch_icon,
            _TEST_IDENTITY.display_name,
        )
    finally:
        user32.DestroyWindow(handle)


@_windows_only
def test_edge_manager_window_keeps_the_ticketbox_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The real case: Edge owns the window (another process) and sets its own app ID first."""
    import time

    assert desktop_shell.discover_edge_executable() is not None, "Microsoft Edge is required for this gate"
    monkeypatch.setattr(desktop_shell, "manager_shell_identity", lambda: _TEST_IDENTITY)
    window = desktop_shell.open_app_window(
        "data:text/html,<title>Ticketbox identity probe</title><p>probe</p>",
        profile=tmp_path / "edge-profile",
    )
    assert window is not None
    try:
        deadline = time.monotonic() + 30
        while not window._stamped and time.monotonic() < deadline:
            window.is_open()
            time.sleep(0.1)
        assert window._stamped, "Edge never showed a window"
        time.sleep(2)  # let the page finish loading; Edge must not take the window back
        live = [handle for handle in desktop_shell._visible_windows(window.process.pid) if handle in window._stamped]
        assert live, "the stamped Edge window disappeared"
        for handle in live:
            assert _read_identity(handle)[:2] == (_TEST_IDENTITY.app_id, _TEST_IDENTITY.relaunch_command)
    finally:
        window.close()
