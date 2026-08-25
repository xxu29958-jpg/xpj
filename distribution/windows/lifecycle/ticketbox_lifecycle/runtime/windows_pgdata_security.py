from __future__ import annotations

import os
import re
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import CommandRunner, require_ok

_FULL_CONTROL = "(OI)(CI)F"
_OWNER_READ_CONTROL = "(OI)(CI)RC"
_OWNER_RIGHTS_SID = "S-1-3-4"


def prepare_initdb_directory(
    runner: CommandRunner,
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
    _replace_tree_acl(
        runner,
        pgdata,
        principal=bootstrap_sid,
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
    _replace_tree_acl(
        runner,
        pgdata,
        principal=service_sid,
        code="pgdata_acl_failed",
    )
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
    _require_policy_path(pgdata, service_sid=service_sid, protected=True)


def _replace_tree_acl(
    runner: CommandRunner,
    path: Path,
    *,
    principal: str,
    code: str,
) -> None:
    require_ok(
        runner.run(["icacls", str(path), "/reset", "/T", "/C", "/L"]),
        code=f"{code}_reset",
    )
    require_ok(
        runner.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{native.SYSTEM_SID}:{_FULL_CONTROL}",
                f"*{native.ADMINISTRATORS_SID}:{_FULL_CONTROL}",
                f"*{principal}:{_FULL_CONTROL}",
                f"*{_OWNER_RIGHTS_SID}:{_OWNER_READ_CONTROL}",
                "/T",
                "/C",
                "/L",
            ]
        ),
        code=code,
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
    paths = [root]
    for parent, directories, files in os.walk(root, topdown=True, followlinks=False):
        paths.extend(Path(parent) / name for name in (*directories, *files))
    for path in paths:
        _require_policy_path(path, service_sid=service_sid, protected=True)


def _require_policy_path(path: Path, *, service_sid: str, protected: bool) -> None:
    native.require_trusted_owner(
        path,
        code="pgdata_owner_untrusted",
        message=f"pgdata object has an untrusted owner: {path.name}",
    )
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
        directory=path.is_dir(),
        protected=protected,
    )


def _require_policy_dacl(
    dacl: str,
    *,
    service_sid: str,
    name: str,
    directory: bool,
    protected: bool,
) -> None:
    expected = {
        native.SYSTEM_SID: "FA",
        native.ADMINISTRATORS_SID: "FA",
        service_sid: "FA",
        _OWNER_RIGHTS_SID: "RC",
    }
    aces = re.findall(r"\(([^()]*)\)", dacl)
    principals: list[str] = []
    for ace in aces:
        fields = ace.split(";")
        principal = {
            "SY": native.SYSTEM_SID,
            "BA": native.ADMINISTRATORS_SID,
            "OW": _OWNER_RIGHTS_SID,
        }.get(fields[5] if len(fields) == 6 else "", "")
        if not principal and len(fields) == 6:
            principal = fields[5]
        flags = fields[1] if len(fields) == 6 else ""
        if (
            len(fields) != 6
            or fields[0] != "A"
            or expected.get(principal) != fields[2]
            or "IO" in flags
            or "NP" in flags
            or (protected and "ID" in flags)
            or (directory and ("OI" not in flags or "CI" not in flags))
        ):
            raise LifecycleError(
                "pgdata_acl_unexpected_principal",
                f"pgdata object has a non-service ACL: {name}",
            )
        principals.append(principal)
    if (
        (protected and not dacl.startswith("D:P"))
        or len(principals) != len(expected)
        or set(principals) != set(expected)
    ):
        raise LifecycleError(
            "pgdata_acl_unexpected_principal",
            f"pgdata object has a non-service ACL: {name}",
        )
