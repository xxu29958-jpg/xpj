from __future__ import annotations

import os
import re
import stat
from functools import lru_cache
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok

ADMINISTRATORS_SID = "S-1-5-32-544"
SYSTEM_SID = "S-1-5-18"
_TRUSTED_OWNER_SIDS = frozenset({ADMINISTRATORS_SID, SYSTEM_SID})
_LIFECYCLE_DIRECTORY_BASE_SDDL = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
_SERVICE_SID_PATTERN = re.compile(r"S-1-5-80-(?:[0-9]+-){4}[0-9]+\Z")
_SID_PATTERN = re.compile(r"S-[0-9]+(?:-[0-9]+)+\Z")
_DACL_INFORMATION = 0x00000004
_BROAD_READER_MARKERS = (
    "BUILTIN\\USERS",
    "NT AUTHORITY\\AUTHENTICATED USERS",
    "EVERYONE",
    "S-1-1-0",
    "S-1-5-11",
    "S-1-5-32-545",
)


def require_windows() -> None:
    if os.name != "nt":
        raise LifecycleError("not_windows", "TicketboxLifecycle.exe only mutates a Windows host")


def has_broad_reader(acl_text: str) -> bool:
    upper = acl_text.upper()
    return any(marker in upper for marker in _BROAD_READER_MARKERS)


def reject_reparse_components(path: Path) -> None:
    cursor = Path(os.path.abspath(path))
    while True:
        try:
            observed = cursor.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise LifecycleViolation("reparse_check_failed", f"cannot inspect path component: {cursor}") from exc
        else:
            attributes = int(getattr(observed, "st_file_attributes", 0))
            reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            if stat.S_ISLNK(observed.st_mode) or attributes & reparse_flag:
                raise LifecycleViolation("reparse_path", f"reparse path component is forbidden: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            return
        cursor = parent


def create_protected_directory(
    path: Path,
    *,
    backend_reader_sid: str,
    interactive_reader_sid: str,
    code: str,
) -> None:
    import ctypes
    from ctypes import wintypes

    require_windows()
    reject_reparse_components(path)

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    create = kernel.CreateDirectoryW
    create.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
    create.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    policy_sddl = _lifecycle_directory_sddl(backend_reader_sid, interactive_reader_sid)
    if not convert(policy_sddl, 1, ctypes.byref(descriptor), None):
        raise LifecycleError(code, "cannot build the lifecycle directory security descriptor")
    attributes = SecurityAttributes(
        ctypes.sizeof(SecurityAttributes),
        descriptor,
        False,
    )
    try:
        if create(str(path), ctypes.byref(attributes)):
            require_protected_directory(
                path,
                backend_reader_sid=backend_reader_sid,
                interactive_reader_sid=interactive_reader_sid,
                code=code,
            )
            return
        error = ctypes.get_last_error()
        if error == 183:
            require_protected_directory(
                path,
                backend_reader_sid=backend_reader_sid,
                interactive_reader_sid=interactive_reader_sid,
                code=code,
            )
            return
        raise LifecycleError(code, f"CreateDirectoryW failed for {path.name}: {error}")
    finally:
        kernel.LocalFree(descriptor)


def require_protected_directory(
    path: Path,
    *,
    backend_reader_sid: str,
    interactive_reader_sid: str,
    code: str,
) -> None:
    reject_reparse_components(path)
    if not path.is_dir():
        raise LifecycleViolation(code, f"lifecycle path is not a directory: {path}")
    require_trusted_owner(
        path,
        code=code,
        message=f"untrusted lifecycle directory: {path}",
    )
    try:
        observed = _directory_security_sddl(path)
    except OSError as exc:
        raise LifecycleViolation(code, f"cannot inspect lifecycle directory: {path}") from exc
    if observed != _canonical_lifecycle_directory_sddl(
        backend_reader_sid,
        interactive_reader_sid,
    ):
        raise LifecycleViolation(code, f"untrusted lifecycle directory: {path}")


def _lifecycle_directory_sddl(backend_reader_sid: str, interactive_reader_sid: str) -> str:
    if _SERVICE_SID_PATTERN.fullmatch(backend_reader_sid) is None:
        raise LifecycleViolation("service_sid_invalid", "backend service SID is not canonical")
    if _SID_PATTERN.fullmatch(interactive_reader_sid) is None:
        raise LifecycleViolation("interactive_sid_invalid", "interactive user SID is not canonical")
    return (
        _LIFECYCLE_DIRECTORY_BASE_SDDL
        + f"(A;;0x000000a0;;;{backend_reader_sid})"
        + f"(A;;0x00000020;;;{interactive_reader_sid})"
    )


@lru_cache(maxsize=8)
def _canonical_lifecycle_directory_sddl(
    backend_reader_sid: str,
    interactive_reader_sid: str,
) -> str:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    policy_sddl = _lifecycle_directory_sddl(backend_reader_sid, interactive_reader_sid)
    if not convert(policy_sddl, 1, ctypes.byref(descriptor), None):
        raise OSError(ctypes.get_last_error(), "cannot canonicalize lifecycle directory SDDL")
    try:
        return _security_descriptor_sddl(descriptor)
    finally:
        kernel.LocalFree(descriptor)


def _directory_security_sddl(path: Path) -> str:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    descriptor = ctypes.c_void_p()
    result = get_security(
        str(path),
        1,
        _DACL_INFORMATION,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise OSError(result, f"GetNamedSecurityInfoW failed for {path}")
    try:
        return _security_descriptor_sddl(descriptor)
    finally:
        kernel.LocalFree(descriptor)


def _security_descriptor_sddl(descriptor) -> str:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    text = wintypes.LPWSTR()
    if not convert(
        descriptor,
        1,
        _DACL_INFORMATION,
        ctypes.byref(text),
        None,
    ):
        raise OSError(ctypes.get_last_error(), "cannot convert Windows security descriptor")
    try:
        return str(text.value)
    finally:
        kernel.LocalFree(text)


def protect_directory(runner: CommandRunner, path: Path, *, code: str) -> None:
    reject_reparse_components(path)
    require_ok(runner.run(["takeown", "/A", "/F", str(path)]), code=f"{code}_owner")
    require_ok(runner.run(["icacls", str(path), "/reset"]), code=code)
    require_ok(
        runner.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{SYSTEM_SID}:(OI)(CI)F",
                f"*{ADMINISTRATORS_SID}:(OI)(CI)F",
            ]
        ),
        code=code,
    )


def protect_file(
    runner: CommandRunner,
    path: Path,
    *,
    extra_grants: tuple[str, ...],
    code: str,
) -> None:
    reject_reparse_components(path)
    if not path.is_file():
        raise LifecycleViolation("credential_invalid", f"not a regular file: {path.name}")
    require_ok(runner.run(["takeown", "/A", "/F", str(path)]), code=f"{code}_owner")
    require_ok(runner.run(["icacls", str(path), "/reset"]), code=code)
    require_ok(
        runner.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{SYSTEM_SID}:(F)",
                f"*{ADMINISTRATORS_SID}:(F)",
                *extra_grants,
            ]
        ),
        code=code,
    )


def service_sid(runner: CommandRunner, service_name: str) -> str:
    completed = runner.run(["sc.exe", "showsid", service_name])
    require_ok(completed, code="service_sid_lookup_failed")
    for token in completed.stdout.replace(",", " ").replace('"', " ").split():
        if token.startswith("S-1-5-80-"):
            return token
    raise LifecycleError("service_sid_lookup_failed", f"SCM did not return a SID for {service_name}")


def require_trusted_owner(path: Path, *, code: str, message: str) -> None:
    try:
        owner_sid = file_owner_sid(path)
    except OSError as exc:
        raise LifecycleViolation(code, message) from exc
    if owner_sid not in _TRUSTED_OWNER_SIDS:
        raise LifecycleViolation(code, message)


def require_protected_file_acl(
    runner: CommandRunner,
    path: Path,
    *,
    code: str,
    required_reader_markers: tuple[str, ...] = (),
    forbidden_markers: tuple[str, ...] = (),
) -> None:
    completed = runner.run(["icacls", str(path)])
    text = f"{completed.stdout}\n{completed.stderr}".upper()
    if completed.returncode != 0 or "(I)" in text:
        raise LifecycleViolation(code, f"{path.name} must have a protected DACL")
    if has_broad_reader(text):
        raise LifecycleViolation(code, f"{path.name} grants a broad Windows principal")
    if any(marker.upper() in text for marker in forbidden_markers):
        raise LifecycleViolation(code, f"{path.name} grants a forbidden Windows principal")
    if not required_reader_markers:
        return
    reader_lines = [
        line
        for line in text.splitlines()
        if any(marker.upper() in line for marker in required_reader_markers)
    ]
    if not reader_lines or any("(R)" not in line for line in reader_lines):
        raise LifecycleViolation(code, f"{path.name} is not read-only for its service reader")
    write_tokens = ("(F)", "(M)", "(W)", "(WD)", "(AD)", "(DC)", "(DE)", "(WO)", "(WA)")
    if any(token in line for line in reader_lines for token in write_tokens):
        raise LifecycleViolation(code, f"{path.name} is writable by its service reader")


def file_owner_sid(path: Path) -> str:
    import ctypes
    from ctypes import wintypes

    if os.name != "nt":
        raise OSError("Windows security descriptors are unavailable")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_named_security_info = advapi.GetNamedSecurityInfoW
    get_named_security_info.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_named_security_info.restype = wintypes.DWORD
    convert_sid = advapi.ConvertSidToStringSidW
    convert_sid.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = get_named_security_info(
        str(path),
        1,
        1,
        ctypes.byref(owner),
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise OSError(result, f"GetNamedSecurityInfoW failed for {path}")
    sid_text = wintypes.LPWSTR()
    try:
        if not convert_sid(owner, ctypes.byref(sid_text)):
            raise OSError(ctypes.get_last_error(), f"ConvertSidToStringSidW failed for {path}")
        return str(sid_text.value)
    finally:
        if sid_text:
            kernel.LocalFree(sid_text)
        if descriptor:
            kernel.LocalFree(descriptor)


def shell_user_sid() -> str | None:
    if os.name != "nt":
        return None
    return _explorer_shell_user_sid() or _linked_token_user_sid()


def _sid_string(advapi, kernel, token) -> str | None:
    import ctypes
    from ctypes import wintypes

    class TokenUser(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    get_info = advapi.GetTokenInformation
    get_info.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_info.restype = wintypes.BOOL
    convert = advapi.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    size = wintypes.DWORD()
    get_info(token, 1, None, 0, ctypes.byref(size))
    if size.value < ctypes.sizeof(TokenUser):
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not get_info(token, 1, buf, size.value, ctypes.byref(size)):
        return None
    sid = TokenUser.from_buffer(buf).Sid
    string_sid = wintypes.LPWSTR()
    if not convert(sid, ctypes.byref(string_sid)):
        return None
    result = string_sid.value
    kernel.LocalFree(string_sid)
    return result


def _linked_token_user_sid() -> str | None:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 19, None, 0, ctypes.byref(size))
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 19, buf, size.value, ctypes.byref(size)):
            return None
        linked = wintypes.HANDLE.from_buffer(buf).value
        if not linked:
            return None
        try:
            return _sid_string(advapi, kernel, linked)
        finally:
            kernel.CloseHandle(linked)
    finally:
        kernel.CloseHandle(token)


def _explorer_shell_user_sid() -> str | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    hwnd = user32.GetShellWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return None
    try:
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            return None
        try:
            return _sid_string(advapi, kernel, token)
        finally:
            kernel.CloseHandle(token)
    finally:
        kernel.CloseHandle(handle)
