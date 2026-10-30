"""Open Desktop Manager URLs in the Windows desktop shell."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import require_local_fixed_regular_file

_CREATE_NO_WINDOW = 0x08000000
_EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"

# The Manager UI is an Edge app window, so Windows would file it under Edge's own
# per-profile app ID: a generic globe, never grouped with the Ticketbox shortcut, and
# a pin that relaunches a deleted throwaway profile. The installer's Start-menu
# shortcut carries this same ID (distribution/windows/installer/ticketbox.iss).
MANAGER_APP_ID = "Ticketbox.Manager"
MANAGER_DISPLAY_NAME = "管理小票夹"


@dataclass(frozen=True)
class ShellIdentity:
    """Taskbar identity stamped onto the Manager's Edge window."""

    app_id: str
    relaunch_command: str
    relaunch_icon: str
    display_name: str


def manager_shell_identity() -> ShellIdentity | None:
    """Only the installed Manager has a stable executable for Windows to relaunch."""
    if not getattr(sys, "frozen", False):
        return None
    executable = os.path.abspath(sys.executable)
    return ShellIdentity(
        app_id=MANAGER_APP_ID,
        relaunch_command=f'"{executable}"',
        # PyInstaller embeds backend/packaging/ticketbox.ico as icon resource 0.
        relaunch_icon=f"{executable},0",
        display_name=MANAGER_DISPLAY_NAME,
    )


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
    identity: ShellIdentity | None = None
    _saw_window: bool = field(default=False, init=False, repr=False)
    _stamped: set[int] = field(default_factory=set, init=False, repr=False)

    def is_open(self) -> bool:
        if self.process.poll() is not None:
            return False
        visible = _visible_windows(self.process.pid)
        if self.identity is not None:
            for handle in visible:
                if handle not in self._stamped:
                    # Once per window: a failure only costs the taskbar grouping.
                    self._stamped.add(handle)
                    with contextlib.suppress(OSError):
                        _apply_shell_identity(handle, self.identity)
        self._saw_window = self._saw_window or bool(visible)
        # Before the first native window appears, the launched process is still starting.
        # Once shown, closing the window ends the UI even if Edge stays in background.
        return bool(visible) or not self._saw_window

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


def _visible_windows(process_id: int) -> list[int]:
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
    visible: list[int] = []

    @callback_type
    def observe(handle, _context):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(handle):
            visible.append(int(handle))
        return True

    if not user32.EnumWindows(observe, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return visible


# System.AppUserModel.* (propkey.h): ID = 5, RelaunchCommand = 2, RelaunchIconResource = 3,
# RelaunchDisplayNameResource = 4. Windows uses them for grouping, pinning and jump lists.
_APP_USER_MODEL_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_VT_LPWSTR = 31


@contextlib.contextmanager
def _window_property_store(handle: int) -> Iterator[tuple[object, object]]:
    """Yield (get_value, set_value) bound to one window's shell property store."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD),
                    ("data3", wintypes.WORD), ("data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        # vt + three reserved words, then the union (a string pointer here).
        _fields_ = [("vt", wintypes.USHORT), ("reserved1", wintypes.WORD), ("reserved2", wintypes.WORD),
                    ("reserved3", wintypes.WORD), ("value", ctypes.c_void_p), ("padding", ctypes.c_void_p)]

    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    ole32.CLSIDFromString.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(GUID))
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    shell32.SHGetPropertyStoreForWindow.argtypes = (wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    hresult = ctypes.c_long

    def guid(text: str) -> GUID:
        value = GUID()
        if ole32.CLSIDFromString(text, ctypes.byref(value)) != 0:
            raise OSError(f"invalid GUID {text}")
        return value

    # COINIT_APARTMENTTHREADED; S_FALSE (1) means already initialised and still needs a matching uninit.
    initialised = ole32.CoInitializeEx(None, 0x2) in (0, 1)
    store = ctypes.c_void_p()
    try:
        status = shell32.SHGetPropertyStoreForWindow(handle, ctypes.byref(guid(_IID_PROPERTY_STORE)), ctypes.byref(store))
        if status != 0 or not store:
            raise OSError(f"SHGetPropertyStoreForWindow failed: {status & 0xFFFFFFFF:#010x}")
        vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
        get_value = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtable[5])
        set_value = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtable[6])
        commit = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p)(vtable[7])
        fmtid = guid(_APP_USER_MODEL_FMTID)

        def read(pid: int) -> str | None:
            value = PROPVARIANT()
            if get_value(store, ctypes.byref(PROPERTYKEY(fmtid, pid)), ctypes.byref(value)) != 0:
                raise OSError("IPropertyStore::GetValue failed")
            if value.vt != _VT_LPWSTR or not value.value:
                return None
            text = ctypes.wstring_at(value.value)
            ole32.CoTaskMemFree(value.value)
            return text

        def write(pid: int, text: str) -> None:
            buffer = ctypes.create_unicode_buffer(text)
            value = PROPVARIANT(vt=_VT_LPWSTR, value=ctypes.cast(buffer, ctypes.c_void_p).value)
            # The store copies the value; Commit makes the taskbar see it now.
            if set_value(store, ctypes.byref(PROPERTYKEY(fmtid, pid)), ctypes.byref(value)) != 0 or commit(store) != 0:
                raise OSError("IPropertyStore::SetValue failed")

        try:
            yield read, write
        finally:
            release(store)
    finally:
        if initialised:
            ole32.CoUninitialize()


def _apply_shell_identity(handle: int, identity: ShellIdentity) -> None:
    # Same order as Chromium's own SetAppDetailsForWindow: the ID, then the relaunch details.
    with _window_property_store(handle) as (_read, write):
        write(5, identity.app_id)
        write(3, identity.relaunch_icon)
        write(2, identity.relaunch_command)
        write(4, identity.display_name)


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
                "--start-maximized",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError:
        return None
    return EdgeAppWindow(process, identity=manager_shell_identity())
