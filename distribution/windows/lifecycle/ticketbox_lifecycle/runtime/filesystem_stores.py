from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.adapters.ports import AdapterBundle
from ticketbox_lifecycle.domain.install import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.mutex import os_mutex
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_security_native import (
    reject_reparse_components,
)
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root
from ticketbox_lifecycle.runtime.windows_services import service_registered
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    ActiveOperation,
    HostObservation,
    InstallationBinding,
    InstallRequest,
)


class FilesystemStores:
    def __init__(
        self,
        machine_root: Path,
        backend_service_name: str,
        adapters: AdapterBundle,
    ) -> None:
        self._machine_root = machine_root
        self._operations_dir = machine_root / "operations"
        self._history_dir = self._operations_dir / "history"
        self._active_path = self._operations_dir / "active.json"
        self._active_temp_path = self._operations_dir / layout.ACTIVE_OPERATION_TEMP_NAME
        self._binding_path = machine_root / "installation.json"
        self._backend_service_name = backend_service_name
        self._adapters = adapters
        self._mutex = os_mutex()

    @classmethod
    def from_request(cls, request: InstallRequest) -> FilesystemStores:
        machine_root = Path(request.program_data_root) / "machine"
        runner = SubprocessCommandRunner()
        file_security = WindowsFileSecurity()
        adapters = WindowsAdapterBundle(runner, file_security)
        return cls(machine_root, request.backend_service_name, adapters)

    def as_lifecycle_stores(self) -> LifecycleStores:
        return LifecycleStores(
            mutex=self._mutex,
            shipment=WindowsShipmentVerifier(ticketbox_install_root()),
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
        reject_reparse_components(self._active_path)
        if not self._active_path.is_file():
            return None
        payload = self._read_verified_json(self._active_path)
        return self._operation_from_payload(payload)

    def read_committed(self, operation_id: str) -> ActiveOperation | None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id):
            raise LifecycleViolation(
                "operation_id_invalid",
                "operation id is not a safe history key",
            )
        path = self._history_dir / f"{operation_id}.json"
        reject_reparse_components(path)
        if not path.is_file():
            return None
        operation = self._operation_from_payload(self._read_verified_json(path))
        if operation.phase != "committed" or operation.operation_id != operation_id:
            raise LifecycleError(
                "committed_history_invalid",
                "history is not the exact committed operation",
            )
        return operation

    @staticmethod
    def _operation_from_payload(payload: dict[str, object]) -> ActiveOperation:
        if payload.get("schema") != OPERATION_SCHEMA:
            raise LifecycleError("bad_operation_schema", "operation schema is not v2")
        return ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=str(payload["operation_id"]),
            kind="install",
            request_hash=str(payload["request_hash"]),
            target_release_id=str(payload["target_release_id"]),
            data_root=str(payload["data_root"]),
            release_manifest_sha256=str(payload["release_manifest_sha256"]),
            backend_port=int(payload["backend_port"]),
            phase=payload["phase"],  # type: ignore[arg-type]
            no_return_point=bool(payload["no_return_point"]),
            last_adapter_result=payload.get("last_adapter_result"),
            install_id=str(payload.get("install_id") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            schema_revision=str(payload.get("schema_revision") or ""),
        )

    def prepare(self, request: InstallRequest) -> None:
        self._adapters.security.prepare_operation_store(request)

    def require_fresh_inputs(self, request: InstallRequest) -> None:
        self._adapters.security.require_fresh_inputs(request)

    def publish_active(self, operation: ActiveOperation) -> None:
        reject_reparse_components(self._active_path)
        reject_reparse_components(self._active_temp_path)
        self._operations_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = _write_exact_temp_json(self._active_temp_path, asdict(operation))
        try:
            self._adapters.security.protect_machine_json(
                tmp_path,
                self._backend_service_name,
            )
            self._adapters.security.verify_machine_json(
                tmp_path,
                self._backend_service_name,
            )
            os.replace(tmp_path, self._active_path)
            self._adapters.security.verify_machine_json(
                self._active_path,
                self._backend_service_name,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def archive_committed(self, operation: ActiveOperation) -> None:
        if operation.phase != "committed":
            raise LifecycleError(
                "archive_requires_commit",
                "refusing to archive a non-committed operation",
            )
        history_path = self._history_dir / f"{operation.operation_id}.json"
        reject_reparse_components(history_path)
        self._history_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = _write_temp_json(history_path, asdict(operation))
        try:
            self._adapters.security.protect_machine_json(
                tmp_path,
                self._backend_service_name,
            )
            self._adapters.security.verify_machine_json(
                tmp_path,
                self._backend_service_name,
            )
            os.replace(tmp_path, history_path)
            self._adapters.security.verify_machine_json(
                history_path,
                self._backend_service_name,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        if self._active_path.exists():
            self._active_path.unlink()

    def read(self) -> InstallationBinding | None:
        reject_reparse_components(self._binding_path)
        if not self._binding_path.is_file():
            return None
        payload = self._read_verified_json(self._binding_path)
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
        reject_reparse_components(self._binding_path)
        self._machine_root.mkdir(parents=True, exist_ok=True)
        tmp_path = _write_temp_json(self._binding_path, asdict(binding))
        try:
            self._adapters.security.grant_backend_binding_read(
                tmp_path,
                binding.backend_service_name,
            )
            self._adapters.security.verify_machine_json(
                tmp_path,
                binding.backend_service_name,
            )
            os.replace(tmp_path, self._binding_path)
            self._adapters.security.verify_machine_json(
                self._binding_path,
                binding.backend_service_name,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _read_verified_json(self, path: Path) -> dict[str, object]:
        self._adapters.security.verify_machine_json(path, self._backend_service_name)
        text = path.read_text(encoding="utf-8")
        self._adapters.security.verify_machine_json(path, self._backend_service_name)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise LifecycleError("machine_state_invalid", f"{path.name} must contain a JSON object")
        return payload


def _write_temp_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        _write_json_fd(fd, payload)
        return Path(tmp_name)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _write_exact_temp_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        _write_json_fd(fd, payload)
        return path
    except BaseException:
        with suppress(OSError):
            os.close(fd)
        if os.path.exists(path):
            os.unlink(path)
        raise


def _write_json_fd(fd: int, payload: dict[str, object]) -> None:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
