"""Strict read-only codec for the installer transaction guard."""

from __future__ import annotations

import json
import ntpath
import os
import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from app.services.secure_file import hold_system_runtime_projection_for_read

GUARD_FILENAME = "installer-runtime-recovery-pending"
_FIELDS = frozenset(
    {"schema", "state", "install_dir", "data_root", "created_at_utc"}
)


class InstallerRuntimeGuardError(RuntimeError):
    """The guard is absent from or contradicts installed host authority."""


class InstalledRuntimeAuthority(NamedTuple):
    runtime_junction: Path
    install_dir: Path
    data_root: Path


class InstallerRuntimeRecoveryGuard(NamedTuple):
    schema: str
    state: str
    install_dir: Path
    data_root: Path
    created_at_utc: datetime


def _canonical_local_path(raw: object, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        raise InstallerRuntimeGuardError(
            f"installer runtime recovery guard {label} is not absolute"
        )
    canonical = Path(os.path.abspath(raw))
    drive, tail = ntpath.splitdrive(str(canonical))
    if re.fullmatch(r"[A-Za-z]:", drive) is None or not tail.startswith("\\"):
        raise InstallerRuntimeGuardError(
            f"installer runtime recovery guard {label} is not local"
        )
    if ntpath.normcase(ntpath.normpath(raw)) != ntpath.normcase(str(canonical)):
        raise InstallerRuntimeGuardError(
            f"installer runtime recovery guard {label} is not canonical"
        )
    return canonical


def read_installer_runtime_recovery_guard(
    guard_path: Path,
    authority: InstalledRuntimeAuthority,
) -> InstallerRuntimeRecoveryGuard | None:
    """Return one validated SYSTEM projection, or None when it is absent."""

    if not os.path.lexists(guard_path):
        return None
    if guard_path.name != GUARD_FILENAME:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard path is not canonical"
        )
    try:
        with hold_system_runtime_projection_for_read(guard_path) as protected:
            encoded = protected.read_bytes()
    except (OSError, ValueError) as exc:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard is not protected"
        ) from exc
    if not 0 < len(encoded) <= 16384:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard size is invalid"
        )
    try:
        payload = json.loads(encoded.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard is malformed"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard is not closed"
        )
    if not all(
        isinstance(payload[field], str)
        for field in _FIELDS
    ):
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard fields are not strings"
        )
    try:
        install_dir = _canonical_local_path(payload["install_dir"], label="install_dir")
        data_root = _canonical_local_path(payload["data_root"], label="data_root")
        created_at = datetime.fromisoformat(
            payload["created_at_utc"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard binding is malformed"
        ) from exc
    guard = InstallerRuntimeRecoveryGuard(
        schema=payload["schema"],
        state=payload["state"],
        install_dir=install_dir,
        data_root=data_root,
        created_at_utc=created_at,
    )
    if (
        guard.schema != "ticketbox-installer-runtime-recovery-guard-v1"
        or guard.state != "installer_transaction_pending"
        or os.path.normcase(str(guard.install_dir))
        != os.path.normcase(str(authority.install_dir))
        or os.path.normcase(str(guard.data_root))
        != os.path.normcase(str(authority.data_root))
        or guard.created_at_utc.tzinfo is None
    ):
        raise InstallerRuntimeGuardError(
            "installer runtime recovery guard binding does not match authority"
        )
    return guard
