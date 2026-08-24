from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

INSTALLATION_SCHEMA = "ticketbox-installed-instance-v1"
OPERATION_SCHEMA = "ticketbox-lifecycle-operation-v1"
REQUEST_SCHEMA = "ticketbox-lifecycle-request-v1"
RESULT_SCHEMA = "ticketbox-lifecycle-result-v1"

CommandName = Literal["install", "resume", "inspect"]
OperationKind = Literal["install"]
DurablePhase = Literal[
    "prepared",
    "data_ready",
    "release_activated",
    "committed",
    "failed_recoverable",
    "manual_intervention",
]
APPLY_SEQUENCE: tuple[str, ...] = (
    "programdata_root",
    "acl",
    "postgres_initdb",
    "scm",
    "start_postgres",
    "roles_database",
    "alembic",
    "start_services",
    "health",
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


@dataclass(frozen=True)
class ApplyStep:
    name: str
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
    phase: DurablePhase
    no_return_point: bool
    last_adapter_result: str | None
    install_id: str = ""
    dataset_id: str = ""
    schema_revision: str = ""


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


@dataclass(frozen=True)
class CommandResult:
    schema: str
    ok: bool
    command: CommandName
    operation_id: str
    phase: DurablePhase
    code: str
    message: str
    installation_published: bool
