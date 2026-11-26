from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

INSTALLATION_SCHEMA = "ticketbox-installed-instance-v1"
OPERATION_SCHEMA = "ticketbox-lifecycle-operation-v2"
REQUEST_SCHEMA = "ticketbox-lifecycle-request-v1"
RESULT_SCHEMA = "ticketbox-lifecycle-result-v2"

CommandName = Literal[
    "install",
    "resume",
    "inspect",
    "restore",
    "upgrade",
    "rollback-upgrade",
    "uninstall",
    "reinstall",
    "purge-data",
]
OperationKind = Literal["install", "restore", "upgrade", "uninstall", "reinstall"]
RestoreMode = Literal["same-environment", "cross-machine"]
ApplyStepName = Literal[
    "programdata_root",
    "acl",
    "postgres_initdb",
    "scm",
    "start_postgres",
    "roles_database",
    "alembic",
    "owner_claim",
    "start_services",
    "health",
]
UpgradeStepName = Literal[
    "stop_services",
    "cold_backup",
    "start_postgres",
    "alembic",
    "scm",
    "start_services",
    "health",
]
UninstallStepName = Literal[
    "stop_services",
    "unregister_services",
    "remove_shortcut",
]
DurablePhase = Literal[
    "prepared",
    "data_ready",
    "release_activated",
    "committed",
    "failed_recoverable",
    "rolled_back_to_previous",
    "manual_intervention",
]
APPLY_SEQUENCE: tuple[ApplyStepName, ...] = (
    "programdata_root",
    "acl",
    "postgres_initdb",
    "scm",
    "start_postgres",
    "roles_database",
    "alembic",
    "owner_claim",
    "start_services",
    "health",
)
UPGRADE_SEQUENCE: tuple[UpgradeStepName, ...] = (
    "stop_services",
    "cold_backup",
    "start_postgres",
    "alembic",
    "scm",
    "start_services",
    "health",
)
REINSTALL_SEQUENCE: tuple[ApplyStepName, ...] = (
    "programdata_root",
    "acl",
    "scm",
    "start_postgres",
    "roles_database",
    "alembic",
    "start_services",
    "health",
)
UNINSTALL_SEQUENCE: tuple[UninstallStepName, ...] = (
    "stop_services",
    "unregister_services",
    "remove_shortcut",
)


@dataclass(frozen=True)
class InstallRequest:
    schema: str
    command: CommandName
    operation_id: str
    request_hash: str
    target_release_id: str
    app_dir: str
    data_root: str
    program_data_root: str
    pg_service_name: str
    backend_service_name: str
    pg_port: int
    backend_port: int
    postgres_major: int
    release_manifest_sha256: str
    install_id: str = ""
    dataset_id: str = ""
    schema_revision: str = ""
    schema_min_compatible: str = ""
    semantic_revision: str = ""
    health_attestation_key: str = ""


@dataclass(frozen=True)
class HostObservation:
    installation_present: bool
    active_operation_present: bool
    active_operation_id: str | None
    active_phase: DurablePhase | None
    program_files_present: bool
    data_root_present: bool
    pgdata_present: bool = False
    pg_service_present: bool = False
    backend_service_present: bool = False
    managed_connector_present: bool = False


@dataclass(frozen=True)
class ApplyStep:
    name: ApplyStepName | UpgradeStepName
    adapter: str


@dataclass(frozen=True)
class InstallPlan:
    kind: OperationKind
    steps: tuple[ApplyStep, ...]


@dataclass(frozen=True)
class ActiveOperation:
    schema: str
    operation_id: str
    kind: OperationKind
    request_hash: str
    target_release_id: str
    data_root: str
    release_manifest_sha256: str
    backend_port: int
    phase: DurablePhase
    no_return_point: bool
    completed_step: ApplyStepName | UpgradeStepName | UninstallStepName | None
    install_id: str = ""
    dataset_id: str = ""
    schema_revision: str = ""
    health_attestation_key: str = ""


@dataclass(frozen=True)
class RestoreOperation(ActiveOperation):
    """Restore's transient authority carries its expected generation before publication."""

    expected_restore_epoch: int = 1


@dataclass(frozen=True)
class UpgradeOperation(ActiveOperation):
    """Upgrade's transient authority preserves existing identity across release cutover."""

    expected_restore_epoch: int = 0
    previous_release_id: str = ""
    previous_release_manifest_sha256: str = ""
    source_schema_revision: str = ""
    backup_path: str = ""
    backup_sha256: str = ""
    business_writes_opened: bool = False


@dataclass(frozen=True)
class ReinstallOperation(ActiveOperation):
    """Preserved-data reinstall keeps existing dataset identity and restore epoch."""

    expected_restore_epoch: int = 0


@dataclass(frozen=True)
class UninstallOperation(ActiveOperation):
    """Controlled uninstall removes program services while preserving data and identity."""

    expected_restore_epoch: int = 0


@dataclass(frozen=True)
class InstallationBinding:
    schema: str
    install_id: str
    dataset_id: str
    expected_restore_epoch: int
    data_root: str
    active_release_id: str
    previous_release_id: str | None
    release_manifest_sha256: str
    postgres_major: int
    pg_service_name: str
    backend_service_name: str
    pg_port: int
    backend_port: int
    health_attestation_key: str


@dataclass(frozen=True)
class OwnerPairing:
    pairing_code: str
    pairing_expires_at: str
    revoked_credentials_summary: dict[str, int] | None = None


@dataclass(frozen=True)
class CommandResult:
    schema: str
    ok: bool
    command: CommandName
    operation_id: str
    phase: DurablePhase
    code: str
    message: str
    installation_published: bool | None
    pairing_code: str = ""
    pairing_expires_at: str = ""
    restore_mode: str = ""
    client_generation: str = ""
    restore_epoch: int | None = None
    revoked_credentials_summary: dict[str, int] | None = None
    client_reconnect_guidance: str = ""
    restored_release_id: str = ""
    quarantine_path: str = ""
    details: dict[str, object] | None = None
