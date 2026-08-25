"""Native validation and in-place IO for the UAC helper result channel."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_trusted_file import (
    file_security_descriptor,
    open_exclusive_file,
)

_SID_PATTERN = re.compile(r"S-1-(?:[0-9]+-)+[0-9]+\Z", re.IGNORECASE)
_ACE_PATTERN = re.compile(r"\(([^()]*)\)")


def channel_file_identity(stream: BinaryIO) -> str:
    info = os.fstat(stream.fileno())
    return f"{info.st_dev:x}:{info.st_ino:x}"


def require_sid(value: str) -> str:
    if not _SID_PATTERN.fullmatch(value):
        raise RuntimeControlError("管理员结果通道 owner SID 格式无效。")
    return value


def validate_exact_file_security(path: Path, caller_sid: str, *, directory: bool = False) -> None:
    """Require caller ownership and one protected full-control ACE per trusted principal."""
    if os.name != "nt":
        return
    owner_sid, sddl = file_security_descriptor(path)
    if owner_sid.casefold() != require_sid(caller_sid).casefold():
        raise RuntimeControlError("管理员结果通道 owner 与发起用户不一致。")
    dacl = sddl.partition("D:")[2]
    if not dacl.startswith("P"):
        raise RuntimeControlError("管理员结果通道 ACL 未禁止继承。")
    aces = _ACE_PATTERN.findall(dacl)
    expected = {"SY", "BA", caller_sid.upper()}
    actual: set[str] = set()
    if len(aces) != len(expected):
        raise RuntimeControlError("管理员结果通道 ACL 包含额外主体。")
    for raw in aces:
        fields = raw.split(";")
        expected_flags = "OICI" if directory else ""
        if len(fields) != 6 or fields[0] != "A" or fields[1] != expected_flags or fields[2] != "FA":
            raise RuntimeControlError("管理员结果通道 ACL 不是精确 FullControl allow 规则。")
        principal = fields[5].upper()
        if principal not in expected or principal in actual:
            raise RuntimeControlError("管理员结果通道 ACL 主体不符合 caller/SYSTEM/Administrators 契约。")
        actual.add(principal)
    if actual != expected:
        raise RuntimeControlError("管理员结果通道 ACL 不完整。")


@contextmanager
def open_exclusive_channel(path: Path) -> Iterator[BinaryIO]:
    """Open the already-created file without following a final reparse point or allowing swaps."""
    with open_exclusive_file(path, writable=True) as stream:
        yield stream
