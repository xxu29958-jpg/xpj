"""Standalone permanent host-data deletion: completely separate from program uninstall."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult, InstallationBinding

ALLOWED_EXTERNAL_BACKUP_STATUSES = frozenset({"preserved_outside", "none_confirmed"})


@dataclass(frozen=True)
class PurgeDataRequest:
    operation_id: str
    dataset_id: str
    confirm_dataset_id: str
    external_backups_status: str
    confirm_permanent_delete: bool
    program_data_root: str


class PurgeDataPlatform(Protocol):
    def require_services_stopped(self, binding: InstallationBinding) -> None: ...

    def verify_local_dataset_identity(
        self,
        binding: InstallationBinding,
        *,
        program_data_root: str,
    ) -> dict[str, object]: ...

    def purge_authorized_local_data(
        self,
        binding: InstallationBinding,
        *,
        program_data_root: str,
    ) -> list[str]: ...


def _is_canonical_uuid(value: str) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def purge_data(
    stores: LifecycleStores,
    request: PurgeDataRequest,
    platform: PurgeDataPlatform,
) -> CommandResult:
    """Explicitly purge verified local host data; never authorized by stale registry/receipt/dir name."""
    if not request.confirm_permanent_delete:
        raise LifecycleViolation(
            "purge_confirmation_required",
            "permanent data deletion requires explicit --confirm-permanent-delete",
        )
    if not _is_canonical_uuid(request.dataset_id) or not _is_canonical_uuid(request.confirm_dataset_id):
        raise LifecycleViolation(
            "purge_dataset_id_invalid",
            "permanent data deletion requires canonical dataset_id and confirm_dataset_id",
        )
    if request.dataset_id != request.confirm_dataset_id:
        raise LifecycleViolation(
            "purge_confirmation_mismatch",
            "dataset_id and confirm_dataset_id must match exactly",
        )
    if request.external_backups_status not in ALLOWED_EXTERNAL_BACKUP_STATUSES:
        raise LifecycleViolation(
            "purge_backup_status_required",
            "explicit external backup status confirmation is required",
        )

    stores.mutex.acquire()
    try:
        return _purge_locked(stores, request, platform)
    finally:
        stores.mutex.release()


def _purge_locked(
    stores: LifecycleStores,
    request: PurgeDataRequest,
    platform: PurgeDataPlatform,
) -> CommandResult:
    active = stores.operations_read.read_active()
    if active is not None:
        raise LifecycleViolation(
            "purge_operation_active",
            "cannot permanently delete data while a lifecycle operation is active",
        )
    binding = stores.binding_read.read()
    if binding is None:
        raise LifecycleViolation(
            "purge_binding_missing",
            "verified installation.json is required to authorize permanent deletion; "
            "stale registry entries, receipts or directory names cannot authorize data deletion",
        )
    if binding.dataset_id != request.dataset_id:
        raise LifecycleViolation(
            "purge_dataset_mismatch",
            "confirmed dataset_id does not match the verified installed dataset_id",
        )
    expected_data_root = os.path.join(request.program_data_root, "data")
    if _norm_path(binding.data_root) != _norm_path(expected_data_root):
        raise LifecycleViolation(
            "purge_path_untrusted",
            "binding data_root does not match the exact protected ProgramData/Ticketbox/data path",
        )
    platform.require_services_stopped(binding)
    verified_identity = platform.verify_local_dataset_identity(
        binding,
        program_data_root=request.program_data_root,
    )
    if (
        verified_identity.get("dataset_id") != request.dataset_id
        or verified_identity.get("client_generation") != binding.install_id
        or verified_identity.get("restore_epoch") != binding.expected_restore_epoch
    ):
        raise LifecycleViolation(
            "purge_dataset_identity_mismatch",
            "verified pgdata identity disagrees with confirmed dataset_id or installation binding",
        )
    purged_paths = platform.purge_authorized_local_data(
        binding,
        program_data_root=request.program_data_root,
    )
    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command="purge-data",
        operation_id=request.operation_id,
        phase="committed",
        code="data_permanently_purged",
        message="Authorized local host dataset permanently deleted; external and cloud backups were not touched.",
        installation_published=False,
        details={
            "dataset_id": request.dataset_id,
            "verified_dataset_identity": verified_identity,
            "data_root": binding.data_root,
            "program_data_root": request.program_data_root,
            "external_backups_status": request.external_backups_status,
            "external_backups_untouched": True,
            "purged_paths": purged_paths,
        },
    )
