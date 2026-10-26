"""Manager-facing error presentation over the shared native Known Folder resolver."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.adapters import windows_known_folders as native

from backend_manager.runtime import RuntimeControlError

PROGRAM_DATA_FOLDER_ID = native.PROGRAM_DATA_FOLDER_ID
DOWNLOADS_FOLDER_ID = native.DOWNLOADS_FOLDER_ID


def known_folder_path(folder_uuid: UUID, *, label: str) -> Path:
    try:
        return native.known_folder_path(folder_uuid)
    except native.KnownFolderError as exc:
        if exc.code == "windows_required":
            message = f"Windows {label} 目录只支持 Windows。"
        elif exc.code == "com_initialization_failed":
            message = f"无法为 Windows Known Folder 初始化 COM（HRESULT=0x{exc.hresult:08x}）。"
        else:
            message = f"无法定位 Windows {label}（HRESULT=0x{exc.hresult:08x}）。"
        raise RuntimeControlError(message) from exc
