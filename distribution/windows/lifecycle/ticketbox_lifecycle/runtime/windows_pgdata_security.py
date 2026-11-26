from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok
from ticketbox_lifecycle.runtime.windows_dacl import apply_protected_dacl, set_owner_sid

_OWNER_RIGHTS_SID = "S-1-3-4"
_LOCAL_SERVICE_SID = "S-1-5-19"
AclShape = Literal["root", "directory", "file"]


def prepare_initdb_directory(
    pgdata: Path,
    *,
    bootstrap_sid: str,
) -> None:
    if native._SID_PATTERN.fullmatch(bootstrap_sid) is None:
        raise LifecycleViolation(
            "initdb_reader_invalid",
            "initdb bootstrap user SID is not canonical",
        )
    native.reject_reparse_components(pgdata)
    if os.path.lexists(pgdata) and not pgdata.is_dir():
        raise LifecycleViolation(
            "pgdata_invalid",
            "PostgreSQL data path must be a directory",
    )
    pgdata.mkdir(exist_ok=True)
    _reject_tree_reparse(pgdata)
    apply_protected_dacl(
        pgdata,
        _root_dacl_sddl(bootstrap_sid),
        code="initdb_directory_acl_failed",
    )


def seal_for_service(
    runner: CommandRunner,
    pgdata: Path,
    *,
    service_sid: str,
) -> None:
    if native._SERVICE_SID_PATTERN.fullmatch(service_sid) is None:
        raise LifecycleViolation("service_sid_invalid", "PostgreSQL service SID is not canonical")
    _reject_tree_reparse(pgdata)
    require_ok(
        runner.run(
            [
                "icacls",
                str(pgdata),
                "/setowner",
                f"*{native.ADMINISTRATORS_SID}",
                "/T",
                "/C",
                "/L",
            ]
        ),
        code="pgdata_owner_failed",
    )
    apply_protected_dacl(
        pgdata,
        _root_dacl_sddl(service_sid),
        code="pgdata_acl_failed",
    )
    _require_exact_tree(pgdata, service_sid=service_sid)


def require_service_policy(
    pgdata: Path,
    *,
    service_sid: str,
    verify_tree: bool,
) -> None:
    if native._SERVICE_SID_PATTERN.fullmatch(service_sid) is None:
        raise LifecycleViolation("service_sid_invalid", "PostgreSQL service SID is not canonical")
    if verify_tree:
        _require_exact_tree(pgdata, service_sid=service_sid)
        return
    native.reject_reparse_components(pgdata)
    if not pgdata.is_dir():
        raise LifecycleViolation("pgdata_invalid", "PostgreSQL data path is not a directory")
    _require_policy_path(pgdata, service_sid=service_sid, shape="root")


def _root_dacl_sddl(principal: str) -> str:
    return (
        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        f"(A;OICI;FA;;;{principal})"
        "(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )


def _raise_pgdata_walk_error(exc: OSError) -> None:
    raise LifecycleError(
        "pgdata_tree_unreadable",
        f"cannot enumerate pgdata tree: {exc.filename or exc}",
    ) from exc


def _reject_tree_reparse(root: Path) -> None:
    native.reject_reparse_components(root)
    if not root.is_dir():
        raise LifecycleViolation("pgdata_invalid", "PostgreSQL data path is not a directory")
    for parent, directories, files in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=_raise_pgdata_walk_error,
    ):
        for name in (*directories, *files):
            native.reject_reparse_components(Path(parent) / name)


def _require_exact_tree(root: Path, *, service_sid: str) -> None:
    _reject_tree_reparse(root)
    _require_policy_path(root, service_sid=service_sid, shape="root")
    for parent, directories, files in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=_raise_pgdata_walk_error,
    ):
        for name in directories:
            _require_policy_path(
                Path(parent) / name,
                service_sid=service_sid,
                shape="directory",
            )
        for name in files:
            _require_policy_path(
                Path(parent) / name,
                service_sid=service_sid,
                shape="file",
            )


def _require_policy_path(path: Path, *, service_sid: str, shape: AclShape) -> None:
    _require_policy_owner(path, service_sid=service_sid, shape=shape)
    try:
        dacl = native._object_dacl_sddl(path)
    except OSError as exc:
        raise LifecycleError(
            "pgdata_acl_verify_failed",
            f"cannot inspect pgdata ACL: {path.name}",
        ) from exc
    _require_policy_dacl(
        dacl,
        service_sid=service_sid,
        name=path.name,
        shape=shape,
    )


def _require_policy_owner(path: Path, *, service_sid: str, shape: AclShape) -> None:
    try:
        owner_sid = native.file_owner_sid(path)
    except OSError as exc:
        raise LifecycleError(
            "pgdata_owner_untrusted",
            f"cannot inspect pgdata owner: {path.name}",
        ) from exc
    allowed = {native.SYSTEM_SID, native.ADMINISTRATORS_SID}
    if shape != "root":
        allowed.update({_LOCAL_SERVICE_SID, service_sid})
    if owner_sid not in allowed:
        raise LifecycleError(
            "pgdata_owner_untrusted",
            f"pgdata object has an untrusted owner: {path.name}",
        )


def _require_policy_dacl(
    dacl: str,
    *,
    service_sid: str,
    name: str,
    shape: AclShape,
) -> None:
    expected = _expected_aces(service_sid, shape)
    aces = re.findall(r"\(([^()]*)\)", dacl)
    observed: list[tuple[str, str, str]] = []
    for ace in aces:
        fields = ace.split(";")
        principal = {
            "SY": native.SYSTEM_SID,
            "BA": native.ADMINISTRATORS_SID,
            "OW": _OWNER_RIGHTS_SID,
        }.get(fields[5] if len(fields) == 6 else "", "")
        if not principal and len(fields) == 6:
            principal = fields[5]
        if (
            len(fields) != 6
            or fields[0] != "A"
            or fields[3]
            or fields[4]
            or not principal
        ):
            raise LifecycleError(
                "pgdata_acl_unexpected_principal",
                f"pgdata object has a non-service ACL: {name}",
            )
        observed.append((principal, fields[2], fields[1]))
    control = dacl[2 : dacl.find("(")] if dacl.startswith("D:") else ""
    expected_control = {"P", "PAI"} if shape == "root" else {"AI"}
    if control not in expected_control or sorted(observed) != sorted(expected):
        raise LifecycleError(
            "pgdata_acl_unexpected_principal",
            f"pgdata object has a non-service ACL: {name}",
        )


def _expected_aces(service_sid: str, shape: AclShape) -> list[tuple[str, str, str]]:
    if shape == "root":
        return [
            (native.SYSTEM_SID, "FA", "OICI"),
            (native.ADMINISTRATORS_SID, "FA", "OICI"),
            (service_sid, "FA", "OICI"),
            (_OWNER_RIGHTS_SID, "RC", ""),
            (_OWNER_RIGHTS_SID, "RC", "OICIIO"),
        ]
    flags = "OICIID" if shape == "directory" else "ID"
    return [
        (native.SYSTEM_SID, "FA", flags),
        (native.ADMINISTRATORS_SID, "FA", flags),
        (service_sid, "FA", flags),
        (_OWNER_RIGHTS_SID, "RC", flags),
    ]


def _dacl_grants_inheritable_full_access(dacl_sddl: str, user_sid: str) -> bool:
    target = user_sid.upper()
    for ace in re.findall(r"\(([^()]*)\)", dacl_sddl):
        fields = ace.split(";")
        if len(fields) != 6 or fields[0] != "A":
            continue
        if fields[5].upper() != target:
            continue
        flags = fields[1].upper()
        rights = fields[2].upper()
        if rights == "FA" and "OI" in flags and "CI" in flags and "IO" not in flags:
            return True
    return False


def _dacl_contains_sid(dacl_sddl: str, user_sid: str) -> bool:
    target = user_sid.upper()
    for ace in re.findall(r"\(([^()]*)\)", dacl_sddl):
        fields = ace.split(";")
        if len(fields) == 6 and fields[5].upper() == target:
            return True
    return False


def _root_dacl_matches(observed_sddl: str, expected_sddl: str) -> bool:
    obs_ctrl = observed_sddl[2 : observed_sddl.find("(")] if observed_sddl.startswith("D:") else ""
    exp_ctrl = expected_sddl[2 : expected_sddl.find("(")] if expected_sddl.startswith("D:") else ""
    if obs_ctrl not in {"P", "PAI"} or obs_ctrl != exp_ctrl:
        return False
    return re.findall(r"\(([^()]*)\)", observed_sddl) == re.findall(
        r"\(([^()]*)\)", expected_sddl
    )


def _restore_probe_created_owners(pgdata: Path, *, probe_user_sid: str, trusted_owner_sid: str) -> None:
    _reject_tree_reparse(pgdata)
    target_owner = (
        trusted_owner_sid
        if trusted_owner_sid == native.ADMINISTRATORS_SID
        else native.ADMINISTRATORS_SID
    )
    for parent, directories, files in os.walk(
        pgdata,
        topdown=True,
        followlinks=False,
        onerror=_raise_pgdata_walk_error,
    ):
        for name in (*directories, *files):
            candidate = Path(parent) / name
            try:
                owner = native.file_owner_sid(candidate)
            except OSError as exc:
                raise LifecycleError(
                    "purge_probe_owner_restore_failed",
                    f"cannot inspect pgdata owner during probe cleanup: {candidate.name}",
                ) from exc
            if owner.upper() == probe_user_sid.upper():
                set_owner_sid(candidate, target_owner, code="purge_probe_owner_restore_failed")


def _verify_probe_access_restored(
    pgdata: Path,
    *,
    probe_user_sid: str,
    expected_root_dacl: str,
    expected_root_owner: str,
) -> None:
    _reject_tree_reparse(pgdata)
    try:
        observed_root = native._object_dacl_sddl(pgdata)
    except OSError as exc:
        raise LifecycleError(
            "purge_probe_acl_restore_failed",
            "cannot verify restored pgdata root DACL after read-only probe",
        ) from exc
    if _dacl_contains_sid(observed_root, probe_user_sid) or not _root_dacl_matches(
        observed_root, expected_root_dacl
    ):
        raise LifecycleError(
            "purge_probe_acl_restore_failed",
            "pgdata root DACL did not match original protected policy after probe cleanup",
        )
    try:
        observed_root_owner = native.file_owner_sid(pgdata)
    except OSError as exc:
        raise LifecycleError(
            "purge_probe_acl_restore_failed",
            "cannot verify restored pgdata root owner after read-only probe",
        ) from exc
    if (
        observed_root_owner not in {native.SYSTEM_SID, native.ADMINISTRATORS_SID}
        or observed_root_owner.upper() != expected_root_owner.upper()
    ):
        raise LifecycleError(
            "purge_probe_acl_restore_failed",
            "pgdata root owner changed during read-only probe",
        )
    for parent, directories, files in os.walk(
        pgdata,
        topdown=True,
        followlinks=False,
        onerror=_raise_pgdata_walk_error,
    ):
        for name in (*directories, *files):
            candidate = Path(parent) / name
            try:
                child_dacl = native._object_dacl_sddl(candidate)
            except OSError as exc:
                raise LifecycleError(
                    "purge_probe_acl_restore_failed",
                    f"cannot verify restored pgdata DACL after probe cleanup: {candidate.name}",
                ) from exc
            if _dacl_contains_sid(child_dacl, probe_user_sid):
                raise LifecycleError(
                    "purge_probe_acl_restore_failed",
                    f"temporary probe ACE remained on pgdata entry: {candidate.name}",
                )
            try:
                child_owner = native.file_owner_sid(candidate)
            except OSError as exc:
                raise LifecycleError(
                    "purge_probe_owner_restore_failed",
                    f"cannot verify restored pgdata owner after probe cleanup: {candidate.name}",
                ) from exc
            if child_owner.upper() == probe_user_sid.upper():
                raise LifecycleError(
                    "purge_probe_owner_restore_failed",
                    f"temporary probe owner remained on pgdata entry: {candidate.name}",
                )


def _inspect_probe_pgdata_security(pgdata: Path, user_sid: str) -> tuple[str, str] | None:
    _reject_tree_reparse(pgdata)
    try:
        original_dacl = native._object_dacl_sddl(pgdata)
    except OSError as exc:
        raise LifecycleError(
            "purge_probe_acl_failed",
            "cannot inspect pgdata DACL before starting read-only probe",
        ) from exc
    if _dacl_grants_inheritable_full_access(original_dacl, user_sid):
        return None
    if not original_dacl.startswith("D:P"):
        raise LifecycleError(
            "purge_probe_acl_unprotected",
            "pgdata root DACL is not protected from inheritance; refusing to mutate ACL for probe",
        )
    try:
        original_owner = native.file_owner_sid(pgdata)
    except OSError as exc:
        raise LifecycleError(
            "purge_probe_acl_failed",
            "cannot inspect pgdata owner before starting read-only probe",
        ) from exc
    if original_owner not in {native.SYSTEM_SID, native.ADMINISTRATORS_SID}:
        raise LifecycleError(
            "purge_probe_owner_untrusted",
            "pgdata root does not have a trusted SYSTEM or Administrators owner; refusing probe",
        )
    return original_dacl, original_owner


def _restore_and_verify_probe_access(
    pgdata: Path,
    *,
    user_sid: str,
    restore_dacl: str,
    original_owner: str,
    body_error: BaseException | None,
) -> None:
    try:
        apply_protected_dacl(pgdata, restore_dacl, code="purge_probe_acl_restore_failed")
        _restore_probe_created_owners(
            pgdata,
            probe_user_sid=user_sid,
            trusted_owner_sid=original_owner,
        )
        _verify_probe_access_restored(
            pgdata,
            probe_user_sid=user_sid,
            expected_root_dacl=restore_dacl,
            expected_root_owner=original_owner,
        )
    except LifecycleError as restore_exc:
        if body_error is not None:
            primary_code = (
                body_error.code if isinstance(body_error, LifecycleError) else type(body_error).__name__
            )
            raise LifecycleError(
                restore_exc.code,
                f"{restore_exc.message} (after {primary_code})",
            ) from body_error
        raise


@contextlib.contextmanager
def temporary_probe_access(pgdata: Path) -> Iterator[None]:
    """Grant the calling administrator's user SID temporary protected access to sealed pgdata
    for pg_ctl's restricted postgres.exe process, then unconditionally restore and verify the full tree."""
    if os.name != "nt":
        yield
        return
    user_sid = native.current_process_user_sid()
    if (
        not user_sid
        or user_sid in {native.SYSTEM_SID, _LOCAL_SERVICE_SID}
        or native._SID_PATTERN.fullmatch(user_sid) is None
    ):
        yield
        return
    inspected = _inspect_probe_pgdata_security(pgdata, user_sid)
    if inspected is None:
        try:
            yield
        finally:
            _reject_tree_reparse(pgdata)
        return
    restore_dacl, original_owner = inspected
    apply_protected_dacl(pgdata, f"{restore_dacl}(A;OICI;FA;;;{user_sid})", code="purge_probe_acl_failed")
    body_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        _restore_and_verify_probe_access(
            pgdata,
            user_sid=user_sid,
            restore_dacl=restore_dacl,
            original_owner=original_owner,
            body_error=body_error,
        )
