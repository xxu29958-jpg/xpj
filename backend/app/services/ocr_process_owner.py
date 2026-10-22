"""Exact ownership of the OCR process tree; never terminate by image name."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time
from contextlib import suppress

from ocr_runtime.native_runtime import WORKER_MEMORY_BYTES


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", ctypes.c_ulong), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_limit", ctypes.c_ulong),
                ("affinity", ctypes.c_size_t), ("priority", ctypes.c_ulong), ("scheduling", ctypes.c_ulong)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in ("user", "kernel", "period_user", "period_kernel")] + [
        (name, ctypes.c_ulong) for name in ("page_faults", "total_processes", "active_processes", "terminated")]


class ProcessTreeOwner:
    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self.handle = None
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel = kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel.TerminateJobObject.restype = ctypes.c_int
        kernel.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                     ctypes.c_ulong, ctypes.c_void_p]
        kernel.QueryInformationJobObject.restype = ctypes.c_int
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x200  # KILL_ON_JOB_CLOSE | JOB_MEMORY
        limits.job_memory = WORKER_MEMORY_BYTES
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not (
            kernel.AssignProcessToJobObject(self.handle, process._handle)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def terminate_and_wait(self, timeout: float) -> None:
        if os.name == "nt" and self.handle:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + timeout
            while True:
                accounting = _Accounting()
                if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                            ctypes.sizeof(accounting), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if accounting.active_processes == 0:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("OCR process tree did not exit")
                time.sleep(0.01)
        elif os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=timeout)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
