"""Exercise the real Windows dialog with the helper's hidden startup setting."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows dialog")


def test_hidden_console_does_not_hide_masked_input():
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.GetDlgItem.argtypes = (wintypes.HWND, ctypes.c_int)
    user.GetDlgItem.restype = wintypes.HWND
    user.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    program = """
from types import SimpleNamespace
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_connector_prompt as prompt
prompt.INPUT_SECONDS = 15
try:
    prompt.confirm_native(SimpleNamespace(action='configure', desired_enabled=True), needs_token=True)
except LifecycleError as exc:
    print(exc.code)
"""
    # A Windows venv launcher delegates to a different process. Observe the
    # interpreter that actually owns the native dialog.
    process = subprocess.Popen([sys._base_executable, "-B", "-c", program],
        cwd=Path(__file__).resolve().parents[1] / "lifecycle", startupinfo=startup,
        creationflags=subprocess.CREATE_NEW_CONSOLE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dialog = None
    try:
        def visit(hwnd, _parameter):
            nonlocal dialog
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == process.pid:
                name = ctypes.create_unicode_buffer(256)
                user.GetClassNameW(hwnd, name, len(name))
                if name.value == "#32770":
                    dialog = hwnd
            return True

        visitor = callback_type(visit)
        deadline = time.monotonic() + 10
        while (dialog is None or not user.IsWindowVisible(dialog)) and process.poll() is None and time.monotonic() < deadline:
            user.EnumWindows(visitor, 0)
            time.sleep(0.05)
        assert dialog is not None, "native prompt was not created"
        assert user.IsWindowVisible(dialog), "hidden startup also hid the required input window"
        edit = user.GetDlgItem(dialog, 100)
        assert edit and user.GetWindowLongW(edit, -16) & 0x20, "input must mask the credential"
        assert user.PostMessageW(dialog, 0x10, 0, 0)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0 and stdout.strip() == "connector_input_cancelled"
        assert stderr == ""
    finally:
        if process.poll() is None:
            if dialog is not None:
                user.PostMessageW(dialog, 0x10, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
