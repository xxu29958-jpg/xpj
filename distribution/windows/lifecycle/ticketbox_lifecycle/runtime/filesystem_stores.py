from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.adapters.ports import AdapterBundle
from ticketbox_lifecycle.domain.install import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.mutex import os_mutex
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle, service_registered
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    ActiveOperation,
    HostObservation,
    InstallationBinding,
    InstallRequest,
)


class FilesystemStores:
    def __init__(self, machine_root: Path, adapters: AdapterBundle) -> None:
        self._machine_root = machine_root
        self._operations_dir = machine_root / "operations"
        self._history_dir = self._operations_dir / "history"
        self._active_path = self._operations_dir / "active.json"
        self._binding_path = machine_root / "installation.json"
        self._adapters = adapters
        self._mutex = os_mutex()

    @classmethod
    def from_request(cls, request: InstallRequest) -> FilesystemStores:
        machine_root = Path(request.program_data_root) / "machine"
        return cls(machine_root, WindowsAdapterBundle())

    def as_lifecycle_stores(self) -> LifecycleStores:
        return LifecycleStores(
            mutex=self._mutex,
            observer=self,
            operations_read=self,
            operations_write=self,
            binding_read=self,
            binding_write=self,
            adapters=self._adapters,
        )

    def observe(self, request: InstallRequest) -> HostObservation:
        active = self.read_active()
        binding = self.read()
        pgdata = Path(request.data_root) / "pgdata" / "PG_VERSION"
        return HostObservation(
            installation_present=binding is not None,
            active_operation_present=active is not None,
            active_operation_id=None if active is None else active.operation_id,
            active_phase=None if active is None else active.phase,
            program_files_present=Path(request.app_dir).exists(),
            data_root_present=Path(request.data_root).exists(),
            pgdata_present=pgdata.is_file(),
            pg_service_present=service_registered(request.pg_service_name),
            backend_service_present=service_registered(request.backend_service_name),
        )

    def read_active(self) -> ActiveOperation | None:
        if not self._active_path.is_file():
            return None
        payload = json.loads(self._active_path.read_text(encoding="utf-8"))
        if payload.get("schema") != OPERATION_SCHEMA:
            raise LifecycleError("bad_operation_schema", "active.json schema is not v1")
        return ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=str(payload["operation_id"]),
            kind="install",
            request_hash=str(payload["request_hash"]),
            target_release_id=str(payload["target_release_id"]),
            phase=payload["phase"],  # type: ignore[arg-type]
            no_return_point=bool(payload["no_return_point"]),
            last_adapter_result=payload.get("last_adapter_result"),
            install_id=str(payload.get("install_id") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            schema_revision=str(payload.get("schema_revision") or ""),
        )

    def publish_active(self, operation: ActiveOperation) -> None:
        self._operations_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._active_path, asdict(operation))

    def archive_committed(self, operation: ActiveOperation) -> None:
        if operation.phase != "committed":
            raise LifecycleError("archive_requires_commit", "refusing to archive a non-committed operation")
        self._history_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._history_dir / f"{operation.operation_id}.json", asdict(operation))
        if self._active_path.exists():
            self._active_path.unlink()

    def read(self) -> InstallationBinding | None:
        if not self._binding_path.is_file():
            return None
        payload = json.loads(self._binding_path.read_text(encoding="utf-8"))
        if payload.get("schema") != INSTALLATION_SCHEMA:
            raise LifecycleError("bad_binding_schema", "installation.json schema is not v1")
        return InstallationBinding(
            schema=INSTALLATION_SCHEMA,
            install_id=str(payload["install_id"]),
            dataset_id=str(payload["dataset_id"]),
            expected_restore_epoch=int(payload["expected_restore_epoch"]),
            data_root=str(payload["data_root"]),
            active_release_id=str(payload["active_release_id"]),
            previous_release_id=payload.get("previous_release_id"),
            release_manifest_sha256=str(payload["release_manifest_sha256"]),
            postgres_major=int(payload["postgres_major"]),
            pg_service_name=str(payload["pg_service_name"]),
            backend_service_name=str(payload["backend_service_name"]),
            pg_port=int(payload["pg_port"]),
            backend_port=int(payload["backend_port"]),
        )

    def publish(self, binding: InstallationBinding) -> None:
        self._machine_root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._binding_path, asdict(binding))
        grant = getattr(self._adapters.security, "grant_backend_binding_read", None)
        if callable(grant):
            grant(self._binding_path, binding.backend_service_name)


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
