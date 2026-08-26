"""Pure contract tests for protected-file Windows identities and SDDL."""

import contextlib
import ctypes
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

import pytest

from app.services import secure_file, secure_file_windows, secure_file_windows_acl
from app.services.secure_file_windows import (
    ADMINISTRATORS_SID,
    SYSTEM_SID,
    _protected_sddl,
)
from app.services.secure_file_windows_acl import (
    _select_dedicated_service_sid,
    current_process_service_sid,
)

_SERVICE_SID = "S-1-5-80-1-2-3-4-5"
_DISABLED_SERVICE_SID = "S-1-5-80-11-12-13-14-15"


class _FakeAdvapi32:
    def __init__(self) -> None:
        self.information_classes: list[int] = []
        self.last_error = 0
        self.sid_by_pointer = {
            1: "S-1-5-19",
            2: "S-1-5-80-0",
            3: _DISABLED_SERVICE_SID,
            4: _SERVICE_SID,
        }

    def OpenProcessToken(  # noqa: N802 - mirrors Win32 API
        self, _process: object, _access: int, token: object
    ) -> bool:
        token._obj.value = 123  # type: ignore[attr-defined]
        return True

    def GetTokenInformation(  # noqa: N802 - mirrors Win32 API
        self,
        _token: object,
        information_class: int,
        buffer: object,
        _length: object,
        required: object,
    ) -> bool:
        self.information_classes.append(information_class)
        assert information_class == 2
        group_type = secure_file_windows._SidAndAttributes
        offset = secure_file_windows._TokenGroups.groups.offset
        total = offset + 4 * ctypes.sizeof(group_type)
        required._obj.value = total  # type: ignore[attr-defined]
        if buffer is None:
            self.last_error = 122
            return False
        address = ctypes.addressof(buffer)
        ctypes.memset(address, 0, total)
        ctypes.cast(address, ctypes.POINTER(wintypes.DWORD)).contents.value = 4
        groups = (group_type * 4).from_address(address + offset)
        for index, (pointer, attributes) in enumerate(
            ((1, 0x00000004), (2, 0x00000004), (3, 0), (4, 0x00000004))
        ):
            groups[index].sid = pointer
            groups[index].attributes = attributes
        return True

    def ConvertSidToStringSidW(  # noqa: N802 - mirrors Win32 API
        self, sid: int, output: object
    ) -> bool:
        output._obj.value = self.sid_by_pointer[sid]  # type: ignore[attr-defined]
        return True


class _FakeKernel32:
    def __init__(self) -> None:
        self.closed: list[int] = []

    @staticmethod
    def GetCurrentProcess() -> int:  # noqa: N802 - mirrors Win32 API
        return -1

    @staticmethod
    def LocalFree(_value: object) -> int:  # noqa: N802 - mirrors Win32 API
        return 0

    def CloseHandle(self, handle: object) -> bool:  # noqa: N802 - mirrors Win32 API
        self.closed.append(int(handle.value))
        return True


def _assert_service_sid_policy() -> None:
    assert (
        _select_dedicated_service_sid(
            (
                ("S-1-5-19", 0x00000004),
                ("S-1-5-80-0", 0x00000004),
                (_SERVICE_SID, 0x00000004),
                ("S-1-5-80-6-7-8-9-10", 0x00000010),
            )
        )
        == _SERVICE_SID
    )
    for groups in (
        (("S-1-5-19", 0x00000004), ("S-1-5-80-0", 0x00000004)),
        ((_SERVICE_SID, 0),),
        ((_SERVICE_SID, 0x00000010),),
        ((_SERVICE_SID, 0x00000004), ("S-1-5-80-6-7-8-9-10", 0x00000004)),
    ):
        with pytest.raises(PermissionError):
            _select_dedicated_service_sid(groups)


def _assert_runtime_projection_acl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = (tmp_path / "runtime-current.json").resolve()
    apis = (object(), object())
    monkeypatch.setattr(secure_file.os, "name", "nt")
    monkeypatch.setattr(secure_file, "_windows_apis", lambda: apis)
    monkeypatch.setattr(
        secure_file,
        "_current_process_service_sid",
        lambda advapi32, kernel32: _SERVICE_SID,
    )

    def reject_token_user(*_args: object) -> str:
        raise AssertionError("runtime projection consulted TokenUser")

    @contextlib.contextmanager
    def hold_exact_projection(
        path: Path,
        *,
        owner_sids: frozenset[str],
        access_rules: dict[str, int],
    ) -> Iterator[Path]:
        assert path == projection
        assert owner_sids == frozenset({SYSTEM_SID})
        assert access_rules == {
            SYSTEM_SID: secure_file._FILE_ALL_ACCESS,
            ADMINISTRATORS_SID: secure_file._FILE_ALL_ACCESS,
            _SERVICE_SID: secure_file._FILE_GENERIC_READ_EXECUTE,
        }
        yield path

    monkeypatch.setattr(secure_file, "_current_process_sid", reject_token_user)
    monkeypatch.setattr(secure_file, "_hold_windows_protected_file", hold_exact_projection)
    with secure_file.hold_system_runtime_projection_for_read(projection) as held:
        assert held == projection


def test_machine_secret_uses_the_installer_owner_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = (tmp_path / "pgpass").resolve()
    monkeypatch.setattr(secure_file.os, "name", "nt")

    @contextlib.contextmanager
    def hold_exact_secret(
        path: Path,
        *,
        owner_sids: frozenset[str],
        access_rules: dict[str, int],
    ) -> Iterator[Path]:
        assert path == secret
        assert owner_sids == frozenset({ADMINISTRATORS_SID})
        assert access_rules == {
            SYSTEM_SID: secure_file._FILE_ALL_ACCESS,
            ADMINISTRATORS_SID: secure_file._FILE_ALL_ACCESS,
        }
        yield path

    monkeypatch.setattr(secure_file, "_hold_windows_protected_file", hold_exact_secret)
    with secure_file.hold_installer_machine_secret_for_read(secret) as held:
        assert held == secret


def test_protected_sddl_deduplicates_system_process_sid() -> None:
    sddl = _protected_sddl(SYSTEM_SID)

    assert sddl.count(f"(A;;FA;;;{SYSTEM_SID})") == 1
    assert sddl.count(f"(A;;FA;;;{ADMINISTRATORS_SID})") == 1
    assert sddl.count("(A;;FA;;;") == 2


def test_protected_sddl_keeps_three_distinct_trustees_for_service_user() -> None:
    service_sid = "S-1-5-21-1-2-3-1001"
    sddl = _protected_sddl(service_sid)

    assert sddl.count(f"(A;;FA;;;{service_sid})") == 1
    assert sddl.count(f"(A;;FA;;;{SYSTEM_SID})") == 1
    assert sddl.count(f"(A;;FA;;;{ADMINISTRATORS_SID})") == 1
    assert sddl.count("(A;;FA;;;") == 3


def test_runtime_projection_selects_one_enabled_dedicated_service_sid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _assert_service_sid_policy()
    advapi32 = _FakeAdvapi32()
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(
        secure_file_windows_acl.ctypes,
        "get_last_error",
        lambda: advapi32.last_error,
        raising=False,
    )
    assert current_process_service_sid(advapi32, kernel32) == _SERVICE_SID
    assert advapi32.information_classes == [2, 2]
    assert kernel32.closed == [123]
    _assert_runtime_projection_acl(monkeypatch, tmp_path)
