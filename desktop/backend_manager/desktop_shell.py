"""Open Desktop Manager URLs in the Windows desktop shell."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend_manager.process import WindowsKillOnCloseJob, spawn_windows_job_process
from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import require_local_fixed_regular_file

_CREATE_NO_WINDOW = 0x08000000
_EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
_EDGE_VISIBLE_WINDOW_STARTUP_GRACE_SECONDS = 10.0


def open_in_browser(url: str) -> bool:
    shell_open = getattr(os, "startfile", None)
    if shell_open is None:
        return False
    try:
        shell_open(url)
    except OSError:
        return False
    return True


def _registered_edge_candidates() -> tuple[Path, ...]:
    if os.name != "nt":
        return ()

    import winreg

    candidates: list[Path] = []
    views = (
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
    )
    for view in views:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                _EDGE_APP_PATH,
                0,
                winreg.KEY_READ | view,
            ) as key:
                raw, _value_type = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        candidate = os.path.expandvars(str(raw).strip().strip('"'))
        if candidate:
            candidates.append(Path(candidate))
    return tuple(candidates)


def discover_edge_executable() -> str | None:
    """Return only an HKLM-registered, local fixed-disk Edge executable."""
    for candidate in _registered_edge_candidates():
        try:
            return str(require_local_fixed_regular_file(candidate, label="Microsoft Edge"))
        except RuntimeControlError:
            continue
    return None


@dataclass
class EdgeAppWindow:
    """One visible Edge app window and its Job-owned browser process tree."""

    process: subprocess.Popen
    job: WindowsKillOnCloseJob | None = None
    _started_at: float = field(default_factory=time.monotonic, repr=False)
    _visible_window_observed: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def is_open(self) -> bool:
        if self._closed:
            return False
        if self.process.poll() is not None:
            self._closed = True
            self._close_job()
            return False
        if self.job is None:
            return True
        try:
            visible = self.job.has_visible_top_level_window()
        except OSError:
            return True
        if visible:
            self._visible_window_observed = True
            return True
        if (
            not self._visible_window_observed
            and time.monotonic() - self._started_at
            < _EDGE_VISIBLE_WINDOW_STARTUP_GRACE_SECONDS
        ):
            return True
        self._closed = True
        self._close_job()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            self.process.wait(timeout=0.5)
        return False

    def close(self, *, timeout: float = 5.0) -> bool:
        if self._closed:
            return True
        if self.process.poll() is not None:
            self._closed = True
            self._close_job()
            return True
        if self.job is not None:
            self._close_job()
            try:
                self.process.wait(timeout=timeout)
                self._closed = True
                return True
            except subprocess.TimeoutExpired:
                pass
        with contextlib.suppress(OSError):
            self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(OSError):
            self.process.kill()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            self.process.wait(timeout=timeout)
        self._closed = self.process.poll() is not None
        return self._closed

    def _close_job(self) -> None:
        job, self.job = self.job, None
        if job is not None:
            job.close()


def open_app_window(url: str, *, profile: Path) -> EdgeAppWindow | None:
    """Open a dedicated, waitable Edge app process for the Manager UI."""
    edge = discover_edge_executable()
    if edge is None:
        return None
    profile_path = Path(os.path.abspath(profile))
    try:
        profile_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        process, job = spawn_windows_job_process(
            [
                edge,
                "--edge-skip-compat-layer-relaunch",
                "--disable-background-mode",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile_path}",
                f"--app={url}",
                "--window-size=820,660",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError:
        return None
    return EdgeAppWindow(process, job)
