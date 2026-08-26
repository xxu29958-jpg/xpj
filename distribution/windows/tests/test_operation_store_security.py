from __future__ import annotations

import ctypes
import multiprocessing
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    REQUEST_SCHEMA,
    ActiveOperation,
    InstallRequest,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows operation-store semantics")


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, **_kwargs) -> CompletedCommand:
        recorded = tuple(str(part) for part in argv)
        self.calls.append(recorded)
        return CompletedCommand(recorded, 0, "ok", "")


class ForbiddenFileSecurity:
    def protect_file(self, *_args, **_kwargs) -> None:
        raise AssertionError("directory-policy tests must not mutate file ACLs")


_FORBIDDEN_FILE_SECURITY = ForbiddenFileSecurity()


@pytest.fixture(autouse=True)
def _unit_directory_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, "file_owner_sid", lambda _path: native.ADMINISTRATORS_SID)
    monkeypatch.setattr(native, "service_sid", lambda _runner, _name: "S-1-5-80-111-222-333-444-555")
    monkeypatch.setattr(native, "shell_user_sid", lambda: "S-1-5-21-9-9-9-1002")

    def create_directory(path: Path, **_kwargs) -> None:
        path.mkdir()

    def require_directory(path: Path, *, code: str, **_kwargs) -> None:
        native.require_trusted_owner(
            path,
            code=code,
            message=f"untrusted lifecycle directory: {path}",
        )

    monkeypatch.setattr(native, "create_protected_directory", create_directory)
    monkeypatch.setattr(native, "require_protected_directory", require_directory)


@contextmanager
def _retained_directory_handle(path: Path) -> Iterator[int]:
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
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
    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x0002 | 0x0004 | 0x0040,
        0x0001 | 0x0002 | 0x0004,
        None,
        3,
        0x02000000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield int(handle)
    finally:
        close_handle(handle)


class _CrashPublicationSecurity:
    def protect_machine_json(self, _path: Path, _reader_service: str) -> None:
        pass

    def verify_machine_json(self, _path: Path, _reader_service: str) -> None:
        pass


def _crash_before_active_replace(machine_root: str, operation: ActiveOperation) -> None:
    from ticketbox_lifecycle.runtime import filesystem_stores

    stores = FilesystemStores(
        Path(machine_root),
        "TicketboxBackend",
        SimpleNamespace(security=_CrashPublicationSecurity()),
        ThreadMutex(),
    )
    filesystem_stores.os.replace = lambda _source, _target: os._exit(73)
    stores.publish_active(operation)


def _request(tmp_path: Path) -> InstallRequest:
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        app_dir=str(tmp_path / "app"),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="b" * 64,
        install_id="22222222-2222-4222-8222-222222222222",
        dataset_id="33333333-3333-4333-8333-333333333333",
        schema_revision="20260821_0001",
    )


def _prepared_operation(request: InstallRequest) -> ActiveOperation:
    return ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id=request.operation_id,
        kind="install",
        request_hash=request.request_hash,
        target_release_id=request.target_release_id,
        data_root=request.data_root,
        release_manifest_sha256=request.release_manifest_sha256,
        backend_port=request.backend_port,
        phase="prepared",
        no_return_point=False,
        last_adapter_result=None,
        install_id=request.install_id or "",
        dataset_id=request.dataset_id or "",
        schema_revision=request.schema_revision,
    )


def test_precreated_root_with_retained_handle_is_rejected_before_acl_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    root = Path(request.program_data_root)
    (root / "machine" / "operations").mkdir(parents=True)
    monkeypatch.setattr(
        native,
        "file_owner_sid",
        lambda path: (
            "S-1-5-21-9-9-9-1002" if Path(path) == root else native.ADMINISTRATORS_SID
        ),
    )
    runner = RecordingRunner()

    with _retained_directory_handle(root) as retained:
        assert retained
        with pytest.raises(LifecycleViolation, match="untrusted lifecycle directory") as caught:
            WindowsSecurityAdapter(runner, _FORBIDDEN_FILE_SECURITY).prepare_operation_store(
                request
            )

    assert caught.value.code == "operation_store_untrusted"
    assert not any(
        call[0].lower() == "takeown"
        or (call[0].lower() == "icacls" and len(call) > 2)
        for call in runner.calls
    )
    assert not (root / "machine" / "operations" / "active.json").exists()


@pytest.mark.parametrize("relative", [".", "machine", "machine/operations"])
def test_exact_protected_partial_root_is_an_admissible_fresh_retry(
    tmp_path: Path,
    relative: str,
) -> None:
    request = _request(tmp_path)
    root = Path(request.program_data_root)
    (root / relative).mkdir(parents=True)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)

    security.require_fresh_inputs(request)
    security.prepare_operation_store(request)

    assert (root / "machine" / "operations").is_dir()


def test_operation_store_wires_manager_reader_only_to_binding_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    observed_interactive_sids: list[str | None] = []

    def record_create(
        path: Path,
        *,
        interactive_reader_sid: str | None,
        **_kwargs,
    ) -> None:
        observed_interactive_sids.append(interactive_reader_sid)
        path.mkdir()

    def record_require(
        _path: Path,
        *,
        interactive_reader_sid: str | None,
        **_kwargs,
    ) -> None:
        observed_interactive_sids.append(interactive_reader_sid)

    monkeypatch.setattr(native, "create_protected_directory", record_create)
    monkeypatch.setattr(native, "require_protected_directory", record_require)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)

    reader_sid = "S-1-5-21-9-9-9-1001"
    monkeypatch.setattr(native, "shell_user_sid", lambda: reader_sid)
    security.prepare_operation_store(request)

    assert observed_interactive_sids == [reader_sid, reader_sid, None]


def test_first_active_hard_crash_discards_only_the_bounded_orphan_on_retry(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)
    security.prepare_operation_store(request)
    operations = Path(request.program_data_root) / "machine" / "operations"
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_before_active_replace,
        args=(str(operations.parent), _prepared_operation(request)),
    )

    process.start()
    process.join(15)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("active publication fault-injection child did not exit")

    assert process.exitcode == 73
    assert not (operations / "active.json").exists()
    assert [path.name for path in operations.iterdir()] == [layout.ACTIVE_OPERATION_TEMP_NAME]
    security.require_fresh_inputs(request)
    security.prepare_operation_store(request)
    assert list(operations.iterdir()) == []
    security.require_fresh_inputs(request)
    stores = FilesystemStores(
        operations.parent,
        request.backend_service_name,
        SimpleNamespace(security=_CrashPublicationSecurity()),
        ThreadMutex(),
    )
    stores.publish_active(_prepared_operation(request))
    assert stores.read_active() == _prepared_operation(request)


@pytest.mark.parametrize(
    "relative",
    ["foreign", "machine/foreign", "machine/operations/active.json.attacker.tmp"],
)
def test_fresh_inputs_reject_every_unrecognized_operation_root_entry(
    tmp_path: Path,
    relative: str,
) -> None:
    request = _request(tmp_path)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)
    security.prepare_operation_store(request)
    unknown = Path(request.program_data_root) / relative
    unknown.parent.mkdir(parents=True, exist_ok=True)
    unknown.write_text("not lifecycle publication evidence", encoding="utf-8")

    with pytest.raises(LifecycleViolation, match="unbound mutable state") as caught:
        security.require_fresh_inputs(request)

    assert caught.value.code == "preexisting_mutable_state"
    assert unknown.is_file()


def test_exact_pending_name_is_not_cleaned_when_it_is_not_a_regular_file(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)
    security.prepare_operation_store(request)
    pending = (
        Path(request.program_data_root)
        / "machine"
        / "operations"
        / layout.ACTIVE_OPERATION_TEMP_NAME
    )
    pending.mkdir()

    with pytest.raises(LifecycleViolation, match="regular file") as caught:
        security.require_fresh_inputs(request)

    assert caught.value.code == "preexisting_mutable_state"
    assert pending.is_dir()


def test_orphan_cleanup_failure_keeps_its_exact_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)
    security = WindowsSecurityAdapter(RecordingRunner(), _FORBIDDEN_FILE_SECURITY)
    security.prepare_operation_store(request)
    pending = (
        Path(request.program_data_root)
        / "machine"
        / "operations"
        / layout.ACTIVE_OPERATION_TEMP_NAME
    )
    pending.write_text("incomplete", encoding="utf-8")
    original_unlink = Path.unlink

    def refuse_pending_unlink(path: Path, *args, **kwargs) -> None:
        if path == pending:
            raise PermissionError("injected cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_pending_unlink)

    with pytest.raises(LifecycleError, match="incomplete active publication") as caught:
        security.prepare_operation_store(request)

    assert caught.value.code == "operation_store_orphan_cleanup_failed"
    assert pending.is_file()
