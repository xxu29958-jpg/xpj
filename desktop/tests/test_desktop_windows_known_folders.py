from __future__ import annotations

import os

import pytest

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_known_folders import (
    PROGRAM_DATA_FOLDER_ID,
    _com_initialized,
    known_folder_path,
)


class _Ole32:
    def __init__(self, result: int) -> None:
        self.result = result
        self.events: list[str] = []

    def CoInitializeEx(self, _reserved, _mode: int) -> int:  # noqa: N802
        self.events.append("initialize")
        return self.result

    def CoUninitialize(self) -> None:  # noqa: N802
        self.events.append("uninitialize")


@pytest.mark.parametrize("result", [0, 1])
def test_known_folder_balances_successful_com_initialization(result: int) -> None:
    ole32 = _Ole32(result)

    with _com_initialized(ole32):
        ole32.events.append("query")

    assert ole32.events == ["initialize", "query", "uninitialize"]


def test_known_folder_uses_an_existing_different_com_apartment_without_uninitializing() -> None:
    ole32 = _Ole32(0x80010106)

    with _com_initialized(ole32):
        ole32.events.append("query")

    assert ole32.events == ["initialize", "query"]


def test_known_folder_rejects_other_com_initialization_failures() -> None:
    ole32 = _Ole32(0x80004005)

    with pytest.raises(RuntimeControlError, match="COM"), _com_initialized(ole32):
        raise AssertionError("query must not run")

    assert ole32.events == ["initialize"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Known Folder contract")
def test_native_program_data_resolution_is_absolute() -> None:
    path = known_folder_path(PROGRAM_DATA_FOLDER_ID, label="ProgramData")

    assert path.is_absolute()
    assert path.name.casefold() == "programdata"
