from __future__ import annotations

import os

import pytest

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_known_folders import (
    PROGRAM_DATA_FOLDER_ID,
    known_folder_path,
)


@pytest.mark.parametrize(("code", "expected"), [
    ("windows_required", "Windows ProgramData 目录只支持 Windows。"),
    ("com_initialization_failed", "无法为 Windows Known Folder 初始化 COM（HRESULT=0x80004005）。"),
    ("folder_unavailable", "无法定位 Windows ProgramData（HRESULT=0x80004005）。"),
])
def test_manager_preserves_known_folder_failure_presentation(monkeypatch, code, expected):
    from ticketbox_lifecycle.adapters import windows_known_folders as native

    def fail(_folder):
        raise native.KnownFolderError(code, 0x80004005)

    monkeypatch.setattr(native, "known_folder_path", fail)
    with pytest.raises(RuntimeControlError) as error:
        known_folder_path(PROGRAM_DATA_FOLDER_ID, label="ProgramData")
    assert str(error.value) == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows Known Folder contract")
def test_native_program_data_resolution_is_absolute() -> None:
    path = known_folder_path(PROGRAM_DATA_FOLDER_ID, label="ProgramData")

    assert path.is_absolute()
    assert path.name.casefold() == "programdata"
