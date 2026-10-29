"""Windows resource signals for recognition admission; never start or stop a model."""

import ctypes
import os
import time
from dataclasses import dataclass

from ocr_runtime.native_runtime import WORKER_MEMORY_BYTES

SAMPLE_SECONDS = 2.0
# Two complete recovery-scan windows distinguish the measured saturated guest
# from its normal warm burst. Enter and leave only after a complete window.
CPU_WINDOW_SECONDS = 4.0


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
        *[(name, ctypes.c_ulonglong) for name in ("physical", "available_physical", "commit", "available_commit",
            "virtual", "available_virtual", "extended_virtual")]]


@dataclass(frozen=True)
class ResourceReading:
    low_memory: bool
    high_memory: bool
    available_physical: int
    available_commit: int
    idle_ticks: int
    total_ticks: int


class WindowsResources:
    def __init__(self) -> None:
        self._kernel = None
        self._handles = []

    def _open(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMemoryResourceNotification.argtypes = [ctypes.c_uint32]
        kernel.CreateMemoryResourceNotification.restype = ctypes.c_void_p
        kernel.QueryMemoryResourceNotification.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        kernel.QueryMemoryResourceNotification.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
        kernel.GlobalMemoryStatusEx.restype = ctypes.c_int
        kernel.GetSystemTimes.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)] * 3
        kernel.GetSystemTimes.restype = ctypes.c_int
        self._kernel = kernel
        for kind in (0, 1):
            handle = kernel.CreateMemoryResourceNotification(kind)
            if not handle:
                error = ctypes.WinError(ctypes.get_last_error())
                self.close()
                raise error
            self._handles.append(handle)

    def read(self) -> ResourceReading | None:
        if os.name != "nt":
            return None  # Non-Windows development has capacity admission only.
        if self._kernel is None:
            self._open()
        states = []
        for handle in self._handles:
            state = ctypes.c_int()
            if not self._kernel.QueryMemoryResourceNotification(handle, ctypes.byref(state)):
                raise ctypes.WinError(ctypes.get_last_error())
            states.append(bool(state.value))
        memory = _MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if not self._kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError(ctypes.get_last_error())
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        if not self._kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ResourceReading(*states, memory.available_physical, memory.available_commit,
            idle.value, kernel.value + user.value)

    def close(self) -> None:
        for handle in self._handles:
            self._kernel.CloseHandle(handle)
        self._handles = []
        self._kernel = None


@dataclass(frozen=True)
class RecognitionPressure:
    memory: bool = False
    cpu: bool = False
    observed: bool = False


class PressureObserver:
    def __init__(self) -> None:
        self.reader = WindowsResources()
        self._last_at = None
        self._previous = None
        self._busy_seconds = self._clear_seconds = 0.0
        self._pressure = RecognitionPressure()

    def sample(self) -> RecognitionPressure:
        instant = time.monotonic()
        if self._last_at is not None and instant - self._last_at < SAMPLE_SECONDS:
            return self._pressure
        reading = self.reader.read()
        if reading is None:
            return self._pressure
        memory = self._pressure.memory
        if reading.low_memory or min(reading.available_physical, reading.available_commit) < WORKER_MEMORY_BYTES:
            memory = True
        elif reading.high_memory:
            memory = False
        cpu = self._cpu_pressure(reading, instant)
        self._pressure = RecognitionPressure(memory, cpu, observed=True)
        self._last_at, self._previous = instant, reading
        return self._pressure

    def _cpu_pressure(self, reading: ResourceReading, instant: float) -> bool:
        cpu = self._pressure.cpu
        if self._previous is None:
            return cpu
        elapsed = instant - self._last_at
        # Kernel time already includes idle time. Zero idle growth over two
        # full windows means saturation, without a universal CPU percentage.
        if reading.total_ticks > self._previous.total_ticks and reading.idle_ticks == self._previous.idle_ticks:
            self._busy_seconds += elapsed
            self._clear_seconds = 0.0
            if self._busy_seconds >= CPU_WINDOW_SECONDS:
                cpu = True
        else:
            self._clear_seconds += elapsed
            self._busy_seconds = 0.0
            if self._clear_seconds >= CPU_WINDOW_SECONDS:
                cpu = False
        return cpu

    def close(self) -> None:
        self.reader.close()
