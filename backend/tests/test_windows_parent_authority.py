from __future__ import annotations

import pytest

from scripts import test_pg_windows_contract as windows_contract

pytestmark = pytest.mark.parallel_safe


def test_parent_handles_validate_each_adjacent_process_generation(monkeypatch) -> None:
    class Kernel32:
        def __init__(self) -> None:
            self.closed: list[int] = []

        @staticmethod
        def GetCurrentProcess() -> int:  # noqa: N802 - fake Win32 API
            return 10

        @staticmethod
        def OpenProcess(  # noqa: N802 - fake Win32 API
            _access: int,
            _inherit: bool,
            process_id: int,
        ) -> int:
            return process_id

        def CloseHandle(self, handle: int) -> None:  # noqa: N802 - fake Win32 API
            self.closed.append(handle)

    kernel32 = Kernel32()
    created = {10: 300, 20: 200, 30: 250}
    monkeypatch.setattr(
        windows_contract,
        "_windows_parent_process_chain",
        lambda: (20, 30),
    )
    monkeypatch.setattr(
        windows_contract,
        "_windows_process_created_filetime",
        lambda _kernel32, handle: created[handle],
    )

    with pytest.raises(RuntimeError, match="generation was reused"):
        windows_contract._windows_parent_process_handles(kernel32)

    assert set(kernel32.closed) == {20, 30}
