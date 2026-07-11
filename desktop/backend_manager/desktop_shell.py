"""Open Desktop Manager URLs in the Windows desktop shell."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000
_EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"


def open_in_browser(url: str) -> None:
    with contextlib.suppress(OSError):
        subprocess.Popen(["cmd", "/c", "start", "", url], creationflags=_CREATE_NO_WINDOW)


def discover_edge_executable() -> str | None:
    from_path = shutil.which("msedge")
    if from_path and Path(from_path).is_file():
        return from_path
    if os.name != "nt":
        return None

    import winreg

    views = {
        getattr(winreg, "KEY_WOW64_64KEY", 0),
        getattr(winreg, "KEY_WOW64_32KEY", 0),
    }
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
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def open_app_window(url: str) -> None:
    """Open a chromeless Edge app window, falling back to the default browser."""
    edge = discover_edge_executable()
    if edge is None:
        open_in_browser(url)
        return
    try:
        subprocess.Popen([edge, f"--app={url}", "--window-size=820,660"], creationflags=_CREATE_NO_WINDOW)
    except OSError:
        open_in_browser(url)
