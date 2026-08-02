"""Exact Windows owner and DACL validation for secure files."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from app.services import secure_file_windows as _windows


def _get_security_info(
    advapi32: object,
    handle: wintypes.HANDLE,
) -> tuple[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]:
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetSecurityInfo(
        handle,
        _windows._SE_FILE_OBJECT,
        _windows._OWNER_SECURITY_INFORMATION | _windows._DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise ctypes.WinError(result)
    return owner, dacl, descriptor


def _validate_descriptor_dacl(advapi32: object, descriptor: object, dacl: object) -> int:
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not advapi32.GetSecurityDescriptorControl(
        descriptor,
        ctypes.byref(control),
        ctypes.byref(revision),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if not control.value & _windows._SE_DACL_PROTECTED or not dacl:
        raise PermissionError("protected file DACL is inherited or missing")
    size = _windows._AclSizeInformation()
    if not advapi32.GetAclInformation(
        dacl,
        ctypes.byref(size),
        ctypes.sizeof(size),
        _windows._ACL_SIZE_INFORMATION_CLASS,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(size.ace_count)


def _validate_access_rules(
    advapi32: object,
    kernel32: object,
    dacl: object,
    *,
    ace_count: int,
    expected_rules: dict[str, int],
) -> None:
    present_sids: set[str] = set()
    for index in range(ace_count):
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        ace = ctypes.cast(
            ace_pointer,
            ctypes.POINTER(_windows._AccessAllowedAce),
        ).contents
        if (
            ace.header.ace_type != _windows._ACCESS_ALLOWED_ACE_TYPE
            or ace.header.ace_flags & _windows._INHERITED_ACE
        ):
            raise PermissionError("protected file contains a non-exact access rule")
        sid_pointer = ctypes.c_void_p(
            ace_pointer.value + _windows._AccessAllowedAce.sid_start.offset
        )
        sid = _windows._sid_string(advapi32, kernel32, sid_pointer)
        if (
            sid not in expected_rules
            or sid in present_sids
            or ace.mask != expected_rules[sid]
        ):
            raise PermissionError("protected file contains an unauthorized access rule")
        present_sids.add(sid)
    if present_sids != set(expected_rules):
        raise PermissionError("protected file DACL is missing an exact access rule")


def validate_file_acl(
    advapi32: object,
    kernel32: object,
    handle: wintypes.HANDLE,
    *,
    owner_sids: frozenset[str] | None = None,
    access_rules: dict[str, int] | None = None,
) -> None:
    owner, dacl, descriptor = _get_security_info(advapi32, handle)
    try:
        current_sid = _windows.current_process_sid(advapi32, kernel32)
        expected_owner_sids = owner_sids or frozenset({current_sid})
        expected_rules = access_rules or {
            current_sid: _windows._FILE_ALL_ACCESS,
            _windows.SYSTEM_SID: _windows._FILE_ALL_ACCESS,
            _windows.ADMINISTRATORS_SID: _windows._FILE_ALL_ACCESS,
        }
        if (
            not owner
            or _windows._sid_string(advapi32, kernel32, owner)
            not in expected_owner_sids
        ):
            raise PermissionError("protected file owner is not authorized")
        ace_count = _validate_descriptor_dacl(advapi32, descriptor, dacl)
        _validate_access_rules(
            advapi32,
            kernel32,
            dacl,
            ace_count=ace_count,
            expected_rules=expected_rules,
        )
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)
