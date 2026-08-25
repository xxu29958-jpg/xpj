from __future__ import annotations

import ctypes
from types import SimpleNamespace

from ticketbox_lifecycle.runtime.mutex import WindowsNamedMutex


def test_abandoned_windows_mutex_is_acquired_for_crash_retry(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    kernel32 = SimpleNamespace(
        CreateMutexW=lambda _security, _owner, name: calls.append(("create", name)) or 7,
        WaitForSingleObject=lambda handle, timeout: calls.append(("wait", (handle, timeout))) or 0x80,
        ReleaseMutex=lambda handle: calls.append(("release", handle)) or True,
        CloseHandle=lambda handle: calls.append(("close", handle)) or True,
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)

    mutex = WindowsNamedMutex()
    mutex.acquire()
    mutex.release()

    assert ("release", 7) in calls
    assert calls[-1] == ("close", 7)
