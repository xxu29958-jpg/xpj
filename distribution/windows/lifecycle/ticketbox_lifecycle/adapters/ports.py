from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ticketbox_lifecycle.schemas import (
    ActiveOperation,
    DurablePhase,
    HostObservation,
    InstallationBinding,
    InstallRequest,
    OwnerPairing,
)


class Mutex(Protocol):
    def acquire(self) -> None: ...
    def release(self) -> None: ...


class OperationReader(Protocol):
    def read_active(self) -> ActiveOperation | None: ...


class OperationPublisher(Protocol):
    def prepare(self, request: InstallRequest) -> None: ...
    def require_fresh_inputs(self, request: InstallRequest) -> None: ...
    def publish_active(self, operation: ActiveOperation) -> None: ...
    def archive_committed(self, operation: ActiveOperation) -> None: ...


class BindingReader(Protocol):
    def read(self) -> InstallationBinding | None: ...


class BindingPublisher(Protocol):
    def publish(self, binding: InstallationBinding) -> None: ...


class HostObserver(Protocol):
    def observe(self, request: InstallRequest) -> HostObservation: ...


class PlatformAdapter(Protocol):
    name: str

    def apply(self, request: InstallRequest, step: str) -> str: ...
    def verify(self, request: InstallRequest, step: str) -> None: ...


class DatasetAdapter(PlatformAdapter, Protocol):
    def claim_owner(self, request: InstallRequest) -> OwnerPairing: ...


class SecurityAdapter(PlatformAdapter, Protocol):
    def prepare_operation_store(self, request: InstallRequest) -> None: ...
    def require_fresh_inputs(self, request: InstallRequest) -> None: ...
    def protect_machine_json(self, path: Path, reader_service: str) -> None: ...
    def verify_machine_json(self, path: Path, reader_service: str) -> None: ...
    def grant_backend_binding_read(self, binding_path: Path, service_name: str) -> None: ...


class AdapterBundle(Protocol):
    files: PlatformAdapter
    security: SecurityAdapter
    postgres: PlatformAdapter
    alembic: PlatformAdapter
    scm: PlatformAdapter
    dataset: DatasetAdapter


def adapter_for_step(bundle: AdapterBundle, step: str) -> PlatformAdapter:
    mapping = {
        "programdata_root": bundle.files,
        "acl": bundle.security,
        "postgres_initdb": bundle.postgres,
        "start_postgres": bundle.postgres,
        "roles_database": bundle.postgres,
        "alembic": bundle.alembic,
        "scm": bundle.scm,
        "start_services": bundle.scm,
        "health": bundle.dataset,
    }
    try:
        return mapping[step]
    except KeyError as exc:
        raise KeyError(step) from exc


def phase_after(step: str) -> DurablePhase:
    if step in {
        "programdata_root",
        "acl",
        "postgres_initdb",
        "scm",
        "start_postgres",
        "roles_database",
        "alembic",
        "owner_claim",
    }:
        return "data_ready"
    if step in {"start_services", "health"}:
        return "release_activated"
    raise KeyError(step)
