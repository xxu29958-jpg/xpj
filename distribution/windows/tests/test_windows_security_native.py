from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime import windows_file_security as file_security
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CompletedCommand


def test_file_dacl_policy_accepts_only_reader_sids() -> None:
    service_sid = "S-1-5-80-111-222-333-444-555"
    interactive_sid = "S-1-5-21-9-9-9-1002"

    assert file_security.file_dacl_sddl((service_sid, interactive_sid)) == (
        "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)"
        f"(A;;FR;;;{service_sid})(A;;FR;;;{interactive_sid})"
    )

    with pytest.raises(LifecycleViolation, match="file reader SID is not canonical"):
        file_security.file_dacl_sddl((f"*{service_sid}:(F)",))


def test_file_security_has_no_icacls_grant_or_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "active.json.pending.tmp"
    path.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []
    applied: list[tuple[Path, tuple[str, ...], str]] = []

    class Runner:
        def run(self, argv, **_kwargs) -> CompletedCommand:
            recorded = tuple(str(part) for part in argv)
            calls.append(recorded)
            return CompletedCommand(recorded, 0, "", "")

    monkeypatch.setattr(
        file_security,
        "_apply_file_dacl",
        lambda target, readers, *, code: applied.append((target, readers, code)),
    )
    reader = "S-1-5-80-111-222-333-444-555"

    file_security.WindowsFileSecurity().protect_file(
        Runner(),
        path,
        reader_sids=(reader,),
        code="machine_state_acl_failed",
    )

    assert calls == [("takeown", "/A", "/F", str(path))]
    assert applied == [(path, (reader,), "machine_state_acl_failed")]


def _restricted_token_file_error(
    path: Path,
    *,
    desired_access: int,
    creation_disposition: int,
) -> int:
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    create_file = kernel.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    open_process_token = advapi.OpenProcessToken
    open_process_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_process_token.restype = wintypes.BOOL
    advapi.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
    advapi.ImpersonateLoggedOnUser.restype = wintypes.BOOL
    advapi.RevertToSelf.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    restricted = wintypes.HANDLE()
    administrators = ctypes.c_void_p()
    convert_sid = advapi.ConvertStringSidToSidW
    convert_sid.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    convert_sid.restype = wintypes.BOOL
    create_restricted = advapi.CreateRestrictedToken
    create_restricted.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SidAndAttributes),
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    create_restricted.restype = wintypes.BOOL
    if not open_process_token(kernel.GetCurrentProcess(), 0x000E, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not convert_sid(native.ADMINISTRATORS_SID, ctypes.byref(administrators)):
            raise ctypes.WinError(ctypes.get_last_error())
        disabled = SidAndAttributes(administrators, 0)
        if not create_restricted(
            token,
            0x00000001,
            1,
            ctypes.byref(disabled),
            0,
            None,
            0,
            None,
            ctypes.byref(restricted),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi.ImpersonateLoggedOnUser(restricted):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.set_last_error(0)
            handle = create_file(
                str(path),
                desired_access,
                0x00000007,
                None,
                creation_disposition,
                0x00000080,
                None,
            )
            if handle != wintypes.HANDLE(-1).value:
                kernel.CloseHandle(handle)
                return 0
            return ctypes.get_last_error()
        finally:
            if not advapi.RevertToSelf():
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if restricted:
            kernel.CloseHandle(restricted)
        if administrators:
            kernel.LocalFree(administrators)
        kernel.CloseHandle(token)


def test_protected_directory_rejects_untrusted_owner_before_acl_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "operation-root"
    path.mkdir()
    acl_read = {"called": False}
    monkeypatch.setattr(native, "file_owner_sid", lambda _path: "S-1-5-21-9-9-9-1002")

    def read_acl(_path: Path) -> str:
        acl_read["called"] = True
        return "trusted"

    monkeypatch.setattr(native, "_object_dacl_sddl", read_acl)

    with pytest.raises(LifecycleViolation, match="untrusted lifecycle directory") as caught:
        native.require_protected_directory(
            path,
            backend_reader_sid="S-1-5-80-111-222-333-444-555",
            interactive_reader_sid="S-1-5-21-9-9-9-1002",
            code="operation_store_untrusted",
        )

    assert caught.value.code == "operation_store_untrusted"
    assert acl_read["called"] is False


def test_protected_directory_requires_the_exact_lifecycle_dacl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "operation-root"
    path.mkdir()
    expected = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    monkeypatch.setattr(native, "file_owner_sid", lambda _path: native.ADMINISTRATORS_SID)
    monkeypatch.setattr(native, "_canonical_lifecycle_directory_sddl", lambda *_sids: expected)
    monkeypatch.setattr(native, "_object_dacl_sddl", lambda _path: expected)

    native.require_protected_directory(
        path,
        backend_reader_sid="S-1-5-80-111-222-333-444-555",
        interactive_reader_sid="S-1-5-21-9-9-9-1002",
        code="operation_store_untrusted",
    )

    monkeypatch.setattr(
        native,
        "_object_dacl_sddl",
        lambda _path: expected + "(A;OICI;FA;;;S-1-5-21-9-9-9-1002)",
    )
    with pytest.raises(LifecycleViolation, match="untrusted lifecycle directory"):
        native.require_protected_directory(
            path,
            backend_reader_sid="S-1-5-80-111-222-333-444-555",
            interactive_reader_sid="S-1-5-21-9-9-9-1002",
            code="operation_store_untrusted",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows SDDL conversion")
def test_lifecycle_directory_sddl_is_valid_and_canonical() -> None:
    backend_sid = "S-1-5-80-2773621439-1206139620-3556766058-292034643-3006528458"
    interactive_sid = "S-1-5-21-9-9-9-1002"
    assert native._canonical_lifecycle_directory_sddl(backend_sid, interactive_sid) == (
        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        f"(A;;WPLO;;;{backend_sid})(A;;WP;;;{interactive_sid})"
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows restricted-token contract")
def test_exact_process_user_reader_survives_postgres_style_restricted_token(
    tmp_path: Path,
) -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if os.environ.get("CI"):
            pytest.fail("Windows restricted-token lane must run as an administrator")
        pytest.skip("restricted-token contract requires an administrator token")
    process_user_sid = native.current_process_user_sid()
    assert process_user_sid is not None
    path = tmp_path / "postgres.pwfile"
    path.write_text("not-a-real-secret\n", encoding="utf-8")
    file_security._apply_file_dacl(path, (), code="secret_acl_failed")
    assert _restricted_token_file_error(
        path,
        desired_access=0x80000000,
        creation_disposition=3,
    ) == 5

    file_security._apply_file_dacl(
        path,
        (process_user_sid,),
        code="secret_acl_failed",
    )
    expected_dacl = file_security.file_dacl_sddl((process_user_sid,))
    assert expected_dacl == (
        "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)" f"(A;;FR;;;{process_user_sid})"
    )
    native.require_protected_file_acl(
        None,
        path,
        code="credential_acl_untrusted",
        expected_dacl_sddl=expected_dacl,
    )
    assert _restricted_token_file_error(
        path,
        desired_access=0x80000000,
        creation_disposition=3,
    ) == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows directory security contract")
def test_create_protected_directory_applies_the_exact_reader_policy(tmp_path: Path) -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        if os.environ.get("CI"):
            pytest.fail("Windows native security lane must run elevated")
        pytest.skip("production CreateDirectoryW contract requires an elevated token")
    backend_sid = "S-1-5-80-2773621439-1206139620-3556766058-292034643-3006528458"
    interactive_sid = native.shell_user_sid()
    assert interactive_sid is not None
    path = tmp_path / "protected-operation-root"

    native.create_protected_directory(
        path,
        backend_reader_sid=backend_sid,
        interactive_reader_sid=interactive_sid,
        code="operation_store_create_failed",
    )
    native.require_protected_directory(
        path,
        backend_reader_sid=backend_sid,
        interactive_reader_sid=interactive_sid,
        code="operation_store_untrusted",
    )

    assert native.file_owner_sid(path) in {
        native.ADMINISTRATORS_SID,
        native.SYSTEM_SID,
    }
    assert _restricted_token_file_error(
        path / "ordinary-user-write.txt",
        desired_access=0x40000000,
        creation_disposition=1,
    ) == 5
    assert not (path / "ordinary-user-write.txt").exists()
