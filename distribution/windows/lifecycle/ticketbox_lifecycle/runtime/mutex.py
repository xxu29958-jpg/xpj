from __future__ import annotations

import threading

from ticketbox_lifecycle.errors import LifecycleError

_MUTEX_NAME = "Global\\TicketboxLifecycle"


class ThreadMutex:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if not self._lock.acquire(blocking=True, timeout=30):
            raise LifecycleError("mutex_timeout", "could not acquire TicketboxLifecycle mutex")

    def release(self) -> None:
        self._lock.release()


class WindowsNamedMutex:
    def __init__(self, name: str = _MUTEX_NAME) -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> None:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise LifecycleError("mutex_create_failed", "CreateMutexW failed for TicketboxLifecycle")
        wait = kernel32.WaitForSingleObject(handle, 30_000)
        # WAIT_OBJECT_0 and WAIT_ABANDONED both transfer mutex ownership.  The
        # latter is the normal crash-retry path after the previous owner dies.
        if wait not in {0, 0x80}:
            kernel32.CloseHandle(handle)
            raise LifecycleError("mutex_timeout", "could not acquire Global\\TicketboxLifecycle")
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = None


def os_mutex() -> ThreadMutex | WindowsNamedMutex:
    import os

    if os.name == "nt":
        return WindowsNamedMutex()
    return ThreadMutex()
