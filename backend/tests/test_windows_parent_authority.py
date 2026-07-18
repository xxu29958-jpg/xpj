from __future__ import annotations

import pytest

from scripts import test_pg_windows_contract as windows_contract

pytestmark = pytest.mark.parallel_safe


@pytest.fixture(autouse=True)
def _clear_declared_parent_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(
        windows_contract.WINDOWS_PARENT_AUTHORITY_PID_ENV,
        raising=False,
    )
    monkeypatch.delenv(
        windows_contract.WINDOWS_PARENT_AUTHORITY_CREATED_ENV,
        raising=False,
    )


class _Kernel32:
    def __init__(self, *, unavailable: set[int] | None = None) -> None:
        self.closed: list[int] = []
        self.unavailable = unavailable or set()

    @staticmethod
    def GetCurrentProcess() -> int:  # noqa: N802 - fake Win32 API
        return 10

    def OpenProcess(  # noqa: N802 - fake Win32 API
        self,
        _access: int,
        _inherit: bool,
        process_id: int,
    ) -> int:
        return 0 if process_id in self.unavailable else process_id

    def CloseHandle(self, handle: int) -> None:  # noqa: N802 - fake Win32 API
        self.closed.append(handle)


def _stub_parent_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    created: dict[int, int],
    failing_times: set[int] | None = None,
) -> None:
    monkeypatch.setattr(
        windows_contract,
        "_windows_parent_process_chain",
        lambda: (20, 30),
    )

    def process_created(_kernel32: object, handle: int) -> int:
        if handle in (failing_times or set()):
            raise OSError("synthetic process time failure")
        return created[handle]

    monkeypatch.setattr(
        windows_contract,
        "_windows_process_created_filetime",
        process_created,
    )


def test_parent_handle_keeps_the_exact_direct_parent_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32()
    _stub_parent_chain(monkeypatch, created={10: 300, 20: 200, 30: 100})

    handle = windows_contract._windows_parent_process_handle(kernel32)

    assert handle == 20
    assert kernel32.closed == []


def test_parent_handle_rejects_an_ambiguous_direct_parent_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for parent_created in (300, 400):
        kernel32 = _Kernel32()
        _stub_parent_chain(
            monkeypatch,
            created={10: 300, 20: parent_created, 30: 100},
        )

        with pytest.raises(RuntimeError, match="generation was reused"):
            windows_contract._windows_parent_process_handle(kernel32)

        assert kernel32.closed == [20]


def test_parent_handle_ignores_deeper_ancestor_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for kernel32, created, failing_times in (
        (_Kernel32(), {10: 300, 20: 200, 30: 400}, set()),
        (_Kernel32(unavailable={30}), {10: 300, 20: 200}, set()),
        (_Kernel32(), {10: 300, 20: 200}, {30}),
    ):
        _stub_parent_chain(
            monkeypatch,
            created=created,
            failing_times=failing_times,
        )

        handle = windows_contract._windows_parent_process_handle(kernel32)

        assert handle == 20
        assert kernel32.closed == []


def test_parent_handle_uses_declared_authority_across_launcher_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32()
    _stub_parent_chain(monkeypatch, created={10: 300, 20: 250, 30: 200})
    monkeypatch.setenv(windows_contract.WINDOWS_PARENT_AUTHORITY_PID_ENV, "30")
    monkeypatch.setenv(
        windows_contract.WINDOWS_PARENT_AUTHORITY_CREATED_ENV,
        "200",
    )

    handle = windows_contract._windows_parent_process_handle(kernel32)

    assert handle == 30
    assert kernel32.closed == []


def test_parent_handle_rejects_reused_declared_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32()
    _stub_parent_chain(monkeypatch, created={10: 300, 20: 250, 30: 201})
    monkeypatch.setenv(windows_contract.WINDOWS_PARENT_AUTHORITY_PID_ENV, "30")
    monkeypatch.setenv(
        windows_contract.WINDOWS_PARENT_AUTHORITY_CREATED_ENV,
        "200",
    )

    with pytest.raises(RuntimeError, match="generation was reused"):
        windows_contract._windows_parent_process_handle(kernel32)

    assert kernel32.closed == [30]


def test_parent_handle_closes_when_watchdog_thread_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel32 = _Kernel32()
    monkeypatch.setattr(windows_contract.os, "name", "nt")
    monkeypatch.setattr(windows_contract, "_windows_process_kernel32", lambda: kernel32)
    monkeypatch.setattr(windows_contract, "_windows_parent_process_handle", lambda _kernel32: 20)
    monkeypatch.setattr(windows_contract, "_PARENT_WATCHDOG_STARTED", False)
    monkeypatch.setattr(
        windows_contract.threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )

    with pytest.raises(RuntimeError, match="thread unavailable"):
        windows_contract.start_windows_parent_watchdog(label="pytest")

    assert kernel32.closed == [20]
