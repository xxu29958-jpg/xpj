"""Real OS process primitives injected into [BackendSupervisor].

Kept separate from the supervision logic so the latter stays unit-testable: these
functions actually touch the OS (spawn uvicorn, tree-kill, HTTP probe)
and are only exercised by the running app, not the unit tests.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import threading
from collections import deque
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000  # don't pop a console window for child processes
_LOG_LINES = 300
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_ulonglong),
        ("write_operation_count", ctypes.c_ulonglong),
        ("other_operation_count", ctypes.c_ulonglong),
        ("read_transfer_count", ctypes.c_ulonglong),
        ("write_transfer_count", ctypes.c_ulonglong),
        ("other_transfer_count", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", ctypes.c_ulong),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_ulong),
        ("scheduling_class", ctypes.c_ulong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class WindowsKillOnCloseJob:
    """One owning job handle; Windows kills every assigned descendant when it closes."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    def close(self) -> None:
        handle, self._handle = self._handle, 0
        if handle:
            kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(handle)

    def __del__(self) -> None:
        self.close()


def _attach_kill_on_close_job(popen: subprocess.Popen[str]) -> WindowsKillOnCloseJob:
    if os.name != "nt":
        raise OSError("Windows Job Object is unavailable on this platform")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    job = WindowsKillOnCloseJob(handle)
    info = _ExtendedLimitInformation()
    info.basic_limit_information.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    try:
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = getattr(popen, "_handle", None)
        if not process_handle or not kernel32.AssignProcessToJobObject(handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        job.close()
        raise
    return job


class UvicornProcess:
    """A spawned uvicorn process whose stdout/stderr is pumped into a ring buffer.

    Satisfies the ``ManagedProcess`` protocol the supervisor depends on.
    """

    def __init__(self, popen: subprocess.Popen[str], job: WindowsKillOnCloseJob | None = None) -> None:
        self._popen = popen
        self._job = job
        self._log: deque[str] = deque(maxlen=_LOG_LINES)
        self._lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def pid(self) -> int:
        return self._popen.pid

    def poll(self) -> int | None:
        result = self._popen.poll()
        if result is not None:
            self._close_job()
        return result

    def recent_log(self) -> list[str]:
        with self._lock:
            return list(self._log)

    def wait(self, timeout: float) -> int:
        try:
            result = self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError from exc
        self._close_job()
        return result

    def terminate_owned(self) -> bool:
        """Terminate this exact owned process tree through its Job handle."""
        if self.poll() is not None:
            return True
        if self._job is None:
            return False
        self._close_job()
        return True

    def _close_job(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            job.close()

    def _pump(self) -> None:
        stream = self._popen.stdout
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            if line:
                with self._lock:
                    self._log.append(line.rstrip())


def spawn_backend(
    *,
    backend_root: Path,
    venv_python: Path,
    data_root: Path,
    host: str,
    port: int,
) -> UvicornProcess:
    """Launch ``uvicorn app.main:app`` from the backend's own venv."""
    child_environment = os.environ.copy()
    child_environment["TICKETBOX_DATA_DIR"] = str(data_root)
    child_environment["XPJ_EXTRA_LOOPBACK_HOSTS"] = f"127.0.0.1:{port}"
    popen = subprocess.Popen(
        [
            str(venv_python), "-m", "uvicorn", "app.main:app",
            "--host", host, "--port", str(port), "--no-access-log",
        ],
        cwd=str(backend_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        env=child_environment,
    )
    try:
        job = _attach_kill_on_close_job(popen)
    except BaseException:
        kill_requested = tree_kill(popen.pid)
        if not kill_requested:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                popen.kill()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            popen.wait(timeout=5)
        raise
    return UvicornProcess(popen, job)


def tree_kill(pid: int) -> bool:
    """Force-kill a process AND its descendants (``/T``).

    uvicorn's worker is a child process; killing only the parent would orphan the
    worker (still bound to the port). ``taskkill /T`` takes down the whole tree, so a
    stop actually frees the port.
    """
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0
