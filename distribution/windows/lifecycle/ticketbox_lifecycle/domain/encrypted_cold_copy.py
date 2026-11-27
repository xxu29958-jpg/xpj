"""Admission and public recovery-point result for an independent copy."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.domain.cold_copy import cold_copy_backup_id
from ticketbox_lifecycle.errors import LifecycleError


def require_separate_key(key: Path, targets: tuple[Path, ...], managed_roots: tuple[Path, ...]) -> None:
    # Inputs are resolved Windows paths. WindowsPath containment is case-insensitive.
    if any(key.is_relative_to(root) for root in managed_roots):
        raise LifecycleError("cold_key_location_invalid", "keep the recovery key outside the installation")
    for target in targets:
        if (key == target or key.is_relative_to(target.parent)
                or (key.parent != Path(key.anchor) and target.is_relative_to(key.parent))):
            raise LifecycleError("cold_key_location_invalid", "keep the recovery key separate from both copies")


def recovery_identity(verified: dict) -> dict[str, object]:
    # Only these public identity fields leave the authenticated archive.
    identity = verified["identity"]
    ids = {}
    for name in ("dataset_id", "install_id"):
        value = identity.get(name)
        try:
            canonical = isinstance(value, str) and str(UUID(value)) == value
        except ValueError:
            canonical = False
        if not canonical:
            raise LifecycleError("cold_identity_invalid", "cold copy lacks its recovery-point identity")
        ids[name] = value
    epoch = identity.get("restore_epoch")
    if type(epoch) is not int or epoch < 0:
        raise LifecycleError("cold_identity_invalid", "cold copy lacks its recovery epoch")
    return {**ids, "restore_epoch": epoch}


def recovery_result(identity: dict, sha256: str) -> dict[str, object]:
    return {"sha256": sha256, "backup_id": cold_copy_backup_id(sha256), "identity": identity}


def recovery_point(verified: dict, sha256: str) -> dict[str, object]:
    return recovery_result(recovery_identity(verified), sha256)
