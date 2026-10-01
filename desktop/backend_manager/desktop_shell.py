"""Open Desktop Manager URLs in the Windows desktop shell."""

from __future__ import annotations

import contextlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import require_local_fixed_regular_file

_CREATE_NO_WINDOW = 0x08000000
_EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
_APP_WINDOW_SIZE = "1180,760"


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
    """Visible windows and cleanup of one dedicated Manager browser process."""

    process: subprocess.Popen
    _saw_window: bool = field(default=False, init=False, repr=False)

    def is_open(self) -> bool:
        if self.process.poll() is not None:
            return False
        visible = _has_visible_window(self.process.pid)
        self._saw_window = self._saw_window or visible
        # Before the first native window appears, the launched process is still starting.
        # Once shown, closing the window ends the UI even if Edge stays in background.
        return visible or not self._saw_window

    def close(self, *, timeout: float = 5.0) -> bool:
        if self.process.poll() is not None:
            return True
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
        return self.process.poll() is not None


def _has_visible_window(process_id: int) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    visible = False

    @callback_type
    def observe(handle, _context):
        nonlocal visible
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(handle):
            visible = True
        return True

    if not user32.EnumWindows(observe, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return visible


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
        process = subprocess.Popen(
            [
                edge,
                "--edge-skip-compat-layer-relaunch",
                "--disable-background-mode",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile_path}",
                f"--app={url}",
                f"--window-size={_APP_WINDOW_SIZE}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError:
        return None
    return EdgeAppWindow(process)
