"""Exact Windows owner and DACL validation for secure files."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from app.services import secure_file_windows as _windows


def _select_dedicated_service_sid(
    groups: tuple[tuple[str, int], ...],
    *,
    require_owner: bool = False,
) -> str:
    candidates = {
        sid
        for sid, attributes in groups
        if attributes & _windows._SE_GROUP_ENABLED
        and (not require_owner or attributes & _windows._SE_GROUP_OWNER)
        and not attributes & _windows._SE_GROUP_USE_FOR_DENY_ONLY
        and len(sid.split("-")) == 9
        and sid.split("-")[:4] == ["S", "1", "5", "80"]
        and all(part.isdecimal() for part in sid.split("-")[4:])
    }
    if len(candidates) != 1:
        raise PermissionError("runtime projection requires one enabled dedicated Windows service SID")
    return next(iter(candidates))


def current_process_service_sid(
    advapi32: object,
    kernel32: object,
    *,
    require_owner: bool = False,
) -> str:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _windows._TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _windows._TOKEN_GROUPS, None, 0, ctypes.byref(required))
        if ctypes.get_last_error() != _windows._ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _windows._TOKEN_GROUPS,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_groups = ctypes.cast(buffer, ctypes.POINTER(_windows._TokenGroups)).contents
        array_type = _windows._SidAndAttributes * int(token_groups.group_count)
        groups = ctypes.cast(
            ctypes.addressof(token_groups) + _windows._TokenGroups.groups.offset,
            ctypes.POINTER(array_type),
        ).contents
        observed: list[tuple[str, int]] = []
        for group in groups:
            sid_string = wintypes.LPWSTR()
            try:
                if not advapi32.ConvertSidToStringSidW(group.sid, ctypes.byref(sid_string)):
                    raise ctypes.WinError(ctypes.get_last_error())
                observed.append((str(sid_string.value), int(group.attributes)))
            finally:
                if sid_string:
                    kernel32.LocalFree(sid_string)
        return _select_dedicated_service_sid(
            tuple(observed),
            require_owner=require_owner,
        )
    finally:
        kernel32.CloseHandle(token)


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
        if ace.header.ace_type != _windows._ACCESS_ALLOWED_ACE_TYPE or ace.header.ace_flags & _windows._INHERITED_ACE:
            raise PermissionError("protected file contains a non-exact access rule")
        sid_pointer = ctypes.c_void_p(ace_pointer.value + _windows._AccessAllowedAce.sid_start.offset)
        sid = _windows._sid_string(advapi32, kernel32, sid_pointer)
        if sid not in expected_rules or sid in present_sids or ace.mask != expected_rules[sid]:
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
        if not owner or _windows._sid_string(advapi32, kernel32, owner) not in expected_owner_sids:
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
