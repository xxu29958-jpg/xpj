from __future__ import annotations

import ctypes
import os

import pytest

from backend_manager import maintenance_gate
from backend_manager.maintenance_gate import manager_maintenance_requested


def _record(process_id: int = 123, high: int = 456, low: int = 789) -> str:
    return f"ticketbox-manager-maintenance-v1|{process_id}|{high}|{low}"


def test_marker_requires_exact_schema_and_live_process_identity(monkeypatch) -> None:
    monkeypatch.setattr(maintenance_gate.os, "name", "nt")
    observed: list[tuple[int, int, int]] = []

    def matches(process_id: int, high: int, low: int) -> bool:
        observed.append((process_id, high, low))
        return True

    assert manager_maintenance_requested(record_reader=lambda: _record(), process_matcher=matches)
    assert observed == [(123, 456, 789)]
    assert not manager_maintenance_requested(record_reader=lambda: None, process_matcher=matches)
    assert not manager_maintenance_requested(record_reader=lambda: _record(), process_matcher=lambda *_: False)


@pytest.mark.parametrize(
    "record_reader,process_matcher",
    [
        (lambda: "malformed", lambda *_: False),
        (lambda: _record(1 << 32), lambda *_: False),
        (lambda: _record(), lambda *_: None),
    ],
)
def test_marker_fails_closed_when_authority_is_malformed_or_indeterminate(
    monkeypatch,
    record_reader,
    process_matcher,
) -> None:
    monkeypatch.setattr(maintenance_gate.os, "name", "nt")
    assert manager_maintenance_requested(
        record_reader=record_reader,
        process_matcher=process_matcher,
    )


def test_marker_fails_closed_when_registry_cannot_be_read(monkeypatch) -> None:
    monkeypatch.setattr(maintenance_gate.os, "name", "nt")

    def denied() -> str | None:
        raise OSError("denied")

    assert manager_maintenance_requested(record_reader=denied)


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity required")
def test_process_identity_rejects_pid_reuse() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(maintenance_gate._FileTime),
        ctypes.POINTER(maintenance_gate._FileTime),
        ctypes.POINTER(maintenance_gate._FileTime),
        ctypes.POINTER(maintenance_gate._FileTime),
    ]
    created = maintenance_gate._FileTime()
    discarded = [maintenance_gate._FileTime() for _ in range(3)]
    assert kernel32.GetProcessTimes(
        kernel32.GetCurrentProcess(),
        ctypes.byref(created),
        *(ctypes.byref(value) for value in discarded),
    )

    assert maintenance_gate._active_process_matches(os.getpid(), created.high, created.low) is True
    assert maintenance_gate._active_process_matches(os.getpid(), created.high, created.low ^ 1) is False
