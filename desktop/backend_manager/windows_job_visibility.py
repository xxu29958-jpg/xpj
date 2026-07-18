"""Windows Job process membership and visible-window queries."""

from __future__ import annotations

import ctypes
import os

_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_ERROR_MORE_DATA = 234
_PROCESS_ID_INITIAL_CAPACITY = 32
_PROCESS_ID_MAX_CAPACITY = 4096


def active_job_process_ids(handle: int) -> frozenset[int]:
    """Return every process generation currently owned by a Windows Job."""

    if not handle:
        return frozenset()
    if os.name != "nt":
        raise OSError("Windows Job Object is unavailable on this platform")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryInformationJobObject.restype = ctypes.c_int
    header_size = ctypes.sizeof(ctypes.c_ulong) * 2
    process_id_size = ctypes.sizeof(ctypes.c_size_t)
    capacity = _PROCESS_ID_INITIAL_CAPACITY
    while capacity <= _PROCESS_ID_MAX_CAPACITY:
        buffer = ctypes.create_string_buffer(header_size + capacity * process_id_size)
        returned = ctypes.c_ulong()
        ctypes.set_last_error(0)
        queried = kernel32.QueryInformationJobObject(
            handle,
            _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(returned),
        )
        assigned = ctypes.c_ulong.from_buffer(buffer, 0).value
        listed = ctypes.c_ulong.from_buffer(
            buffer,
            ctypes.sizeof(ctypes.c_ulong),
        ).value
        if queried and listed >= assigned:
            process_ids = (ctypes.c_size_t * listed).from_buffer(
                buffer,
                header_size,
            )
            return frozenset(int(process_id) for process_id in process_ids)
        error = ctypes.get_last_error()
        if not queried and error != _ERROR_MORE_DATA:
            raise ctypes.WinError(error or 1)
        required = max(capacity * 2, int(assigned), int(listed))
        capacity = required if required > capacity else capacity * 2
    raise OSError("Windows Job Object process list exceeded the supported bound")


def job_has_visible_top_level_window(handle: int) -> bool:
    """Report whether a process in a Windows Job owns a visible top-level window."""

    process_ids = active_job_process_ids(handle)
    if not process_ids:
        return False
    user32 = ctypes.WinDLL("User32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    found = False

    @callback_type
    def inspect(window: int, _context: int) -> int:
        nonlocal found
        if not user32.IsWindowVisible(window):
            return 1
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if int(process_id.value) in process_ids:
            found = True
            return 0
        return 1

    ctypes.set_last_error(0)
    enumerated = user32.EnumWindows(inspect, None)
    error = ctypes.get_last_error()
    if not enumerated and not found and error:
        raise ctypes.WinError(error)
    return found
