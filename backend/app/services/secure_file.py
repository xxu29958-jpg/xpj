"""Creation-time protection for short-lived secret files."""

from __future__ import annotations

import contextlib
import ctypes
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from app.services import secure_file_windows as _windows
from app.services import secure_file_windows_acl as _windows_acl

_MOVEFILE_WRITE_THROUGH = 0x00000008
_MOVEFILE_REPLACE_EXISTING = 0x00000001
_SYSTEM_SID = _windows.SYSTEM_SID
_ADMINISTRATORS_SID = _windows.ADMINISTRATORS_SID
_FILE_ALL_ACCESS = _windows.FILE_ALL_ACCESS
_FILE_GENERIC_READ_EXECUTE = _windows.FILE_GENERIC_READ_EXECUTE


def _validate_unix_directory_entry(
    directory: os.stat_result,
    *,
    child_owner: int,
) -> None:
    if not stat.S_ISDIR(directory.st_mode):
        raise ValueError("protected file parent chain contains a non-directory")
    effective_uid = os.geteuid()
    if directory.st_uid not in {0, effective_uid}:
        raise PermissionError("protected file parent directory has an untrusted owner")
    if directory.st_mode & 0o022 and (not directory.st_mode & stat.S_ISVTX or child_owner != effective_uid):
        raise PermissionError("protected file parent directory is mutable by another user")


@contextlib.contextmanager
def _open_unix_parent(path: Path) -> Iterator[tuple[int, os.stat_result, str]]:
    lexical = Path(os.path.abspath(path))
    if not path.is_absolute() or not lexical.anchor or not lexical.name:
        raise ValueError("protected file path must be an absolute file path")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lexical.anchor, flags)
    try:
        current = os.fstat(descriptor)
        for component in lexical.parts[1:-1]:
            child_descriptor = os.open(component, flags, dir_fd=descriptor)
            try:
                child = os.fstat(child_descriptor)
                _validate_unix_directory_entry(current, child_owner=child.st_uid)
            except (OSError, ValueError):
                os.close(child_descriptor)
                raise
            os.close(descriptor)
            descriptor = child_descriptor
            current = child
        yield descriptor, current, lexical.name
    finally:
        os.close(descriptor)


def _windows_apis() -> tuple[object, object]:
    return _windows.windows_apis()


def windows_process_start_filetime(process_id: int) -> tuple[int, int]:
    """Return the immutable Windows creation FILETIME for one live process."""

    return _windows.process_start_filetime(process_id, apis=_windows_apis())


def _current_process_sid(advapi32: object, kernel32: object) -> str:
    return _windows.current_process_sid(advapi32, kernel32)


def _current_process_service_sid(advapi32: object, kernel32: object) -> str:
    return _windows_acl.current_process_service_sid(advapi32, kernel32)


@contextlib.contextmanager
def _hold_windows_protected_file(
    path: Path,
    *,
    owner_sids: frozenset[str] | None = None,
    access_rules: dict[str, int] | None = None,
) -> Iterator[Path]:
    with _windows.hold_protected_file(
        path,
        apis=_windows_apis(),
        owner_sids=owner_sids,
        access_rules=access_rules,
    ) as resolved:
        yield resolved


@contextlib.contextmanager
def hold_protected_file_for_read(path: Path) -> Iterator[Path]:
    """Hold a validated secret file so Windows cannot replace it during use."""
    if not path.is_absolute():
        raise ValueError("protected file path must be absolute")
    if os.name == "nt":
        with _hold_windows_protected_file(path) as resolved:
            yield resolved
        return

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    with _open_unix_parent(path) as (parent, parent_metadata, name):
        descriptor = os.open(name, flags, dir_fd=parent)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("protected file must be a regular non-symlink file")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise PermissionError("protected file permissions are too broad")
            if metadata.st_uid != os.geteuid():
                raise PermissionError("protected file owner does not match the current user")
            _validate_unix_directory_entry(parent_metadata, child_owner=metadata.st_uid)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (visible.st_dev, visible.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise OSError("protected file changed while it was being opened")
            yield Path(os.path.abspath(path))
        finally:
            os.close(descriptor)


@contextlib.contextmanager
def hold_system_authority_file_for_read(path: Path) -> Iterator[Path]:
    """Hold a host authority artifact owned by SYSTEM with exact SY/BA ACL."""

    if not path.is_absolute():
        raise ValueError("host authority path must be absolute")
    if os.name != "nt":
        raise OSError("SYSTEM-owned host authority is a Windows-only contract")
    with _hold_windows_protected_file(
        path,
        owner_sids=frozenset({_SYSTEM_SID}),
        access_rules={
            _SYSTEM_SID: _FILE_ALL_ACCESS,
            _ADMINISTRATORS_SID: _FILE_ALL_ACCESS,
        },
    ) as resolved:
        yield resolved


@contextlib.contextmanager
def hold_system_runtime_projection_for_read(path: Path) -> Iterator[Path]:
    """Hold the SYSTEM-owned lifecycle projection exposed to this service SID."""

    if not path.is_absolute():
        raise ValueError("runtime projection path must be absolute")
    if os.name != "nt":
        raise OSError("SYSTEM-owned runtime projection is a Windows-only contract")
    advapi32, kernel32 = _windows_apis()
    service_sid = _current_process_service_sid(advapi32, kernel32)
    if service_sid in {_SYSTEM_SID, _ADMINISTRATORS_SID}:
        raise PermissionError("runtime projection must be read by the dedicated backend service identity")
    with _hold_windows_protected_file(
        path,
        owner_sids=frozenset({_SYSTEM_SID}),
        access_rules={
            _SYSTEM_SID: _FILE_ALL_ACCESS,
            _ADMINISTRATORS_SID: _FILE_ALL_ACCESS,
            service_sid: _FILE_GENERIC_READ_EXECUTE,
        },
    ) as resolved:
        yield resolved


@contextlib.contextmanager
def hold_service_owned_projection_for_read(path: Path) -> Iterator[Path]:
    """Hold a projection owned and written only by this service SID."""
    if not path.is_absolute():
        raise ValueError("service projection path must be absolute")
    if os.name != "nt":
        with hold_protected_file_for_read(path) as resolved:
            yield resolved
        return
    advapi32, kernel32 = _windows_apis()
    service_sid = _windows_acl.current_process_service_sid(advapi32, kernel32)
    with _hold_windows_protected_file(
        path,
        owner_sids=frozenset({service_sid}),
        access_rules={
            service_sid: _FILE_ALL_ACCESS,
            _SYSTEM_SID: _FILE_ALL_ACCESS,
            _ADMINISTRATORS_SID: _FILE_ALL_ACCESS,
        },
    ) as resolved:
        yield resolved


def _write_windows_protected_file(
    path: Path,
    payload: bytes,
    *,
    owner_sid: str | None = None,
) -> None:
    _windows.write_protected_file(
        path,
        payload,
        apis=_windows_apis(),
        owner_sid=owner_sid,
    )


def write_protected_file_exclusive(path: Path, text: str) -> None:
    """Create a new file whose secret is never visible under inherited ACLs."""
    payload = text.encode("utf-8")
    if os.name == "nt":
        _write_windows_protected_file(path, payload)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    with _open_unix_parent(path) as (parent, parent_metadata, name):
        _validate_unix_directory_entry(parent_metadata, child_owner=os.geteuid())
        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())


def _windows_service_projection_authority() -> tuple[str, dict[str, int]]:
    advapi32, kernel32 = _windows_apis()
    service_sid = _windows_acl.current_process_service_sid(
        advapi32,
        kernel32,
        require_owner=True,
    )
    return service_sid, {
        service_sid: _FILE_ALL_ACCESS,
        _SYSTEM_SID: _FILE_ALL_ACCESS,
        _ADMINISTRATORS_SID: _FILE_ALL_ACCESS,
    }


def _publish_windows_file_replace(
    source: Path,
    destination: Path,
    *,
    owner_sid: str,
    access_rules: dict[str, int],
) -> None:
    owner_sids = frozenset({owner_sid})
    with _hold_windows_protected_file(
        source,
        owner_sids=owner_sids,
        access_rules=access_rules,
    ) as resolved_source:
        source_identity = (int(resolved_source.stat().st_dev), int(resolved_source.stat().st_ino))
    if os.path.lexists(destination):
        with _hold_windows_protected_file(
            destination,
            owner_sids=owner_sids,
            access_rules=access_rules,
        ):
            pass
    _advapi32, kernel32 = _windows_apis()
    if not kernel32.MoveFileExW(
        str(source),
        str(destination),
        _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    with _hold_windows_protected_file(
        destination,
        owner_sids=owner_sids,
        access_rules=access_rules,
    ) as resolved_destination:
        destination_identity = (
            int(resolved_destination.stat().st_dev),
            int(resolved_destination.stat().st_ino),
        )
    if destination_identity != source_identity:
        raise OSError("protected replacement changed volume or file identity")


def write_protected_file_replace(
    path: Path,
    text: str,
    *,
    service_owned: bool,
) -> None:
    """Atomically replace one bounded projection under an exact writer ACL."""
    if not path.is_absolute() or not path.name:
        raise ValueError("protected replacement path must be an absolute file path")
    staging = path.parent / f".{path.name}.{uuid4()}.staging"
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        if os.name == "nt" and service_owned:
            owner_sid, access_rules = _windows_service_projection_authority()
            _write_windows_protected_file(
                staging,
                text.encode("utf-8"),
                owner_sid=owner_sid,
            )
            _publish_windows_file_replace(
                staging,
                path,
                owner_sid=owner_sid,
                access_rules=access_rules,
            )
        else:
            write_protected_file_exclusive(staging, text)
            if os.name == "nt":
                owner_sid = _current_process_sid(*_windows_apis())
                access_rules = {
                    owner_sid: _FILE_ALL_ACCESS,
                    _SYSTEM_SID: _FILE_ALL_ACCESS,
                    _ADMINISTRATORS_SID: _FILE_ALL_ACCESS,
                }
                _publish_windows_file_replace(
                    staging,
                    path,
                    owner_sid=owner_sid,
                    access_rules=access_rules,
                )
            else:
                if path.exists():
                    with hold_protected_file_for_read(path):
                        pass
                os.replace(staging, path)
                with hold_protected_file_for_read(path):
                    _fsync_unix_directory(path.parent)
    except BaseException as exc:  # noqa: BLE001 - preserve publication failure
        primary = exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup failure
            if primary is None:
                primary = exc
            else:
                cleanup.append(exc)
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "protected replacement and cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary


def _publish_windows_file_no_replace(source: Path, destination: Path) -> None:
    # Validate the protected source immediately before the namespace move.
    # Its exact DACL prevents an unprivileged writer from replacing it after
    # this handle closes.
    with _hold_windows_protected_file(source) as resolved_source:
        source_metadata = resolved_source.stat()
        source_identity = (
            int(source_metadata.st_dev),
            int(source_metadata.st_ino),
        )
    _advapi32, kernel32 = _windows_apis()
    if not kernel32.MoveFileExW(
        str(source),
        str(destination),
        _MOVEFILE_WRITE_THROUGH,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    with _hold_windows_protected_file(destination) as resolved_destination:
        destination_metadata = resolved_destination.stat()
        destination_identity = (
            int(destination_metadata.st_dev),
            int(destination_metadata.st_ino),
        )
    if destination_identity != source_identity:
        raise OSError("protected publication changed volume or file identity")


def _fsync_unix_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_protected_file_no_replace(
    source: Path,
    destination: Path,
) -> None:
    """Publish a protected file without overwriting an existing authority.

    Windows uses a write-through move. POSIX first makes the destination link
    durable, then removes the staging name and flushes the directory again.
    Both paths leave an existing destination untouched.
    """

    if not source.is_absolute() or not destination.is_absolute():
        raise ValueError("protected publication paths must be absolute")
    source_parent = os.path.normcase(os.path.abspath(source.parent))
    destination_parent = os.path.normcase(os.path.abspath(destination.parent))
    if source_parent != destination_parent or source == destination:
        raise ValueError("protected publication requires distinct names in one directory")
    if os.name == "nt":
        _publish_windows_file_no_replace(source, destination)
        return

    with hold_protected_file_for_read(source):
        os.link(source, destination, follow_symlinks=False)
        with hold_protected_file_for_read(destination):
            _fsync_unix_directory(destination.parent)
        source.unlink()
        _fsync_unix_directory(destination.parent)
