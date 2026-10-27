from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.adapters.windows_known_folders import KnownFolderError, known_folder_path
from ticketbox_lifecycle.errors import LifecycleViolation

_FOLDERID_PROGRAM_FILES = UUID("905e63b6-c1bf-494e-b29c-65b732d3d21a")
_FOLDERID_PROGRAM_FILES_COMMON_X64 = UUID("6365d5a7-0f0d-45e5-87f6-0da56b6a4f7d")
_FOLDERID_PROGRAM_DATA = UUID("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97")


def ticketbox_install_root() -> Path:
    return _known_folder(
        _FOLDERID_PROGRAM_FILES,
        code="program_files_unavailable",
        label="Program Files",
    ) / "Ticketbox"


def ticketbox_control_root() -> Path:
    return _known_folder(
        _FOLDERID_PROGRAM_FILES_COMMON_X64,
        code="common_files_unavailable",
        label="Common Files x64",
    ) / "Ticketbox"


def ticketbox_program_data_root() -> Path:
    return _known_folder(
        _FOLDERID_PROGRAM_DATA,
        code="program_data_unavailable",
        label="ProgramData",
    ) / "Ticketbox"


def _known_folder(folder_uuid: UUID, *, code: str, label: str) -> Path:
    try:
        return known_folder_path(folder_uuid)
    except KnownFolderError as exc:
        if exc.code == "windows_required":
            raise LifecycleViolation(exc.code, f"{label} requires Windows") from exc
        if exc.code == "com_initialization_failed":
            raise LifecycleViolation(exc.code,
                f"cannot initialize COM for Windows Known Folders (HRESULT=0x{exc.hresult:08x})") from exc
        raise LifecycleViolation(code,
            f"cannot resolve the Windows {label} known folder (HRESULT=0x{exc.hresult:08x})") from exc
