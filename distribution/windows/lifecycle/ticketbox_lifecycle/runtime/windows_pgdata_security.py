from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.windows_dacl import apply_protected_dacl
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok

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


def _reject_tree_reparse(root: Path) -> None:
    native.reject_reparse_components(root)
    if not root.is_dir():
        raise LifecycleViolation("pgdata_invalid", "PostgreSQL data path is not a directory")
    for parent, directories, files in os.walk(root, topdown=True, followlinks=False):
        for name in (*directories, *files):
            native.reject_reparse_components(Path(parent) / name)


def _require_exact_tree(root: Path, *, service_sid: str) -> None:
    _reject_tree_reparse(root)
    _require_policy_path(root, service_sid=service_sid, shape="root")
    for parent, directories, files in os.walk(root, topdown=True, followlinks=False):
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
