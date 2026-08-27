from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime import windows_dacl, windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok

_FILE_DACL_BASE_SDDL = "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)"
class FileSecurity(Protocol):
    def protect_file(
        self,
        runner: CommandRunner,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None: ...


class WindowsFileSecurity:
    def protect_file(
        self,
        runner: CommandRunner,
        path: Path,
        *,
        reader_sids: tuple[str, ...],
        code: str,
    ) -> None:
        native.reject_reparse_components(path)
        if not path.is_file():
            raise LifecycleViolation("credential_invalid", f"not a regular file: {path.name}")
        require_ok(runner.run(["takeown", "/A", "/F", str(path)]), code=f"{code}_owner")
        windows_dacl.apply_protected_dacl(
            path,
            file_dacl_sddl(reader_sids),
            code=code,
        )


def file_dacl_sddl(reader_sids: tuple[str, ...]) -> str:
    if any(native._SID_PATTERN.fullmatch(sid) is None for sid in reader_sids):
        raise LifecycleViolation("file_reader_sid_invalid", "file reader SID is not canonical")
    return _FILE_DACL_BASE_SDDL + "".join(f"(A;;FR;;;{sid})" for sid in reader_sids)
