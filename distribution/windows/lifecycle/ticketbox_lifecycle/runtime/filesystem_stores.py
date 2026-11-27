from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.adapters.ports import AdapterBundle, Mutex
from ticketbox_lifecycle.connector_schema import ConnectorOperation
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_store_io import (
    _RELEASE_ID_PATTERN,
    _reject_duplicate_json_keys,
    _write_exact_temp_json,
    _write_temp_json,
    binding_from_payload,
    operation_from_payload,
)
from ticketbox_lifecycle.runtime.filesystem_store_io import (
    _managed_connector_present as _probe_managed_connector_present,
)
from ticketbox_lifecycle.runtime.mutex import os_mutex
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_control_root,
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import service_registered
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import (
    ActiveOperation,
    HostObservation,
    InstallationBinding,
    InstallRequest,
    UpgradeOperation,
)

__all__ = [
    "FilesystemStores",
    "_managed_connector_present",
    "_reject_duplicate_json_keys",
    "_write_exact_temp_json",
    "_write_temp_json",
]


def _managed_connector_present(
    machine_root: Path,
    *,
    binding: InstallationBinding | None = None,
    allowed_manifest_shas: frozenset[str] = frozenset(),
    verify_state_file: Callable[[Path], None] | None = None,
) -> bool:
    return _probe_managed_connector_present(
        machine_root,
        binding=binding,
        allowed_manifest_shas=allowed_manifest_shas,
        verify_state_file=verify_state_file,
        is_service_registered=service_registered,
        reject_reparse=reject_reparse_components,
    )


class FilesystemStores:
    def __init__(
        self,
        machine_root: Path,
        backend_service_name: str,
        adapters: AdapterBundle,
        mutex: Mutex,
        *,
        install_root: Path | None = None,
        program_data_root: Path | None = None,
    ) -> None:
        self._machine_root = machine_root
        self._operations_dir = machine_root / "operations"
        self._history_dir = self._operations_dir / "history"
        self._active_path = self._operations_dir / "active.json"
        self._active_temp_path = self._operations_dir / layout.ACTIVE_OPERATION_TEMP_NAME
        self._binding_path = machine_root / "installation.json"
        self._backend_service_name = backend_service_name
        self._adapters = adapters
        self._mutex = mutex
        self._install_root = install_root
        self._program_data_root = program_data_root

    @classmethod
    def from_installed(
        cls,
        *,
        install_root: Path | None = None,
        program_data_root: Path | None = None,
    ) -> FilesystemStores:
        """Resolve installed authority without accepting Setup paths or commands."""
        resolved_program_data = (
            program_data_root if program_data_root is not None else ticketbox_program_data_root()
        )
        return cls(
            resolved_program_data / "machine",
            "TicketboxBackend",
            WindowsAdapterBundle(SubprocessCommandRunner(), WindowsFileSecurity(), NativeWindowsScmObserver()),
            os_mutex(ticketbox_control_root() / "lifecycle.lock"),
            install_root=install_root,
            program_data_root=resolved_program_data,
        )

    @classmethod
    def from_request(
        cls,
        request: InstallRequest,
        *,
        install_root: Path | None = None,
        program_data_root: Path | None = None,
    ) -> FilesystemStores:
        machine_root = Path(request.program_data_root) / "machine"
        runner = SubprocessCommandRunner()
        file_security = WindowsFileSecurity()
        adapters = WindowsAdapterBundle(runner, file_security, NativeWindowsScmObserver())
        mutex = os_mutex(ticketbox_control_root() / "lifecycle.lock")
        return cls(
            machine_root,
            request.backend_service_name,
            adapters,
            mutex,
            install_root=install_root,
            program_data_root=program_data_root,
        )

    def as_lifecycle_stores(
        self,
        *,
        install_root: Path | None = None,
        program_data_root: Path | None = None,
    ) -> LifecycleStores:
        resolved_install = (
            install_root
            if install_root is not None
            else (self._install_root if self._install_root is not None else ticketbox_install_root())
        )
        resolved_program_data = (
            program_data_root
            if program_data_root is not None
            else (
                self._program_data_root
                if self._program_data_root is not None
                else ticketbox_program_data_root()
            )
        )
        return LifecycleStores(
            mutex=self._mutex,
            shipment=WindowsShipmentVerifier(
                resolved_install,
                resolved_program_data,
            ),
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
        allowed_connector_shas: set[str] = set()
        if binding is not None:
            allowed_connector_shas.add(binding.release_manifest_sha256)
            if (
                isinstance(active, UpgradeOperation)
                and active.operation_id == request.operation_id
                and binding.active_release_id == active.target_release_id
                and active.previous_release_id
            ):
                if re.fullmatch(r"[0-9a-f]{64}", active.previous_release_manifest_sha256):
                    allowed_connector_shas.add(active.previous_release_manifest_sha256)
                prev_manifest = (
                    Path(request.app_dir)
                    / "releases"
                    / active.previous_release_id
                    / "release-manifest.json"
                )
                with suppress(OSError, LifecycleError):
                    reject_reparse_components(prev_manifest)
                    if prev_manifest.is_file():
                        allowed_connector_shas.add(
                            hashlib.sha256(prev_manifest.read_bytes()).hexdigest()
                        )
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
            managed_connector_present=_managed_connector_present(
                self._machine_root,
                binding=binding,
                allowed_manifest_shas=frozenset(allowed_connector_shas),
                verify_state_file=lambda path: self._adapters.security.verify_machine_json(
                    path,
                    self._backend_service_name,
                ),
            ),
        )

    def read_active(self) -> ActiveOperation | ConnectorOperation | None:
        reject_reparse_components(self._active_path)
        if not os.path.lexists(self._active_path):
            return None
        if not self._active_path.is_file():
            raise LifecycleError(
                "machine_state_invalid",
                f"{self._active_path.name} must be a regular file",
            )
        payload = self._read_verified_json(
            self._active_path,
            self._adapters.security.verify_machine_json,
        )
        return self._operation_from_payload(payload)

    def read_committed(self, operation_id: str) -> ActiveOperation | ConnectorOperation | None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id):
            raise LifecycleViolation(
                "operation_id_invalid",
                "operation id is not a safe history key",
            )
        path = self._history_dir / f"{operation_id}.json"
        reject_reparse_components(path)
        if not os.path.lexists(path):
            return None
        if not path.is_file():
            raise LifecycleError(
                "machine_state_invalid",
                f"{path.name} must be a regular file",
            )
        operation = self._operation_from_payload(
            self._read_verified_json(
                path,
                self._adapters.security.verify_machine_json,
            )
        )
        if operation.phase != "committed" or operation.operation_id != operation_id:
            raise LifecycleError(
                "committed_history_invalid",
                "history is not the exact committed operation",
            )
        return operation

    def list_committed(self) -> tuple[ActiveOperation | ConnectorOperation, ...]:
        reject_reparse_components(self._history_dir)
        if not self._history_dir.is_dir():
            return ()
        records: list[ActiveOperation | ConnectorOperation] = []
        for path in sorted(self._history_dir.glob("*.json"), key=lambda item: item.name.casefold()):
            reject_reparse_components(path)
            if not path.is_file():
                continue
            operation = self._operation_from_payload(
                self._read_verified_json(
                    path,
                    self._adapters.security.verify_machine_json,
                )
            )
            if operation.phase != "committed" or f"{operation.operation_id}.json" != path.name:
                raise LifecycleError(
                    "committed_history_invalid",
                    "history contains an invalid committed operation",
                )
            records.append(operation)
        return tuple(records)

    def written_strictly_after_binding(
        self,
        operation_id: str,
        *,
        is_active: bool = False,
    ) -> bool:
        pattern = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        if not re.fullmatch(pattern, operation_id):
            return False
        target_path = self._active_path if is_active else (self._history_dir / f"{operation_id}.json")
        reject_reparse_components(target_path)
        reject_reparse_components(self._binding_path)
        if not target_path.is_file() or not self._binding_path.is_file():
            return False
        return target_path.stat().st_mtime_ns > self._binding_path.stat().st_mtime_ns

    def committed_strictly_after(
        self,
        earlier_operation_id: str,
        later_operation_id: str,
        *,
        later_is_active: bool = False,
    ) -> bool:
        pattern = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        if not re.fullmatch(pattern, earlier_operation_id) or not re.fullmatch(pattern, later_operation_id):
            return False
        earlier_path = self._history_dir / f"{earlier_operation_id}.json"
        later_path = self._active_path if later_is_active else (self._history_dir / f"{later_operation_id}.json")
        reject_reparse_components(earlier_path)
        reject_reparse_components(later_path)
        reject_reparse_components(self._binding_path)
        if not earlier_path.is_file() or not later_path.is_file() or not self._binding_path.is_file():
            return False
        earlier_ns = earlier_path.stat().st_mtime_ns
        later_ns = later_path.stat().st_mtime_ns
        binding_ns = self._binding_path.stat().st_mtime_ns
        return later_ns > earlier_ns and later_ns > binding_ns

    def known_sibling_releases(
        self,
        binding: InstallationBinding | None,
        *,
        exclude_release_id: str | None = None,
    ) -> frozenset[str]:
        if binding is None:
            return frozenset()
        releases: set[str] = set()
        for rid in (binding.active_release_id, binding.previous_release_id):
            if isinstance(rid, str) and _RELEASE_ID_PATTERN.fullmatch(rid):
                releases.add(rid)
        for record in self.list_committed():
            if not isinstance(record, ActiveOperation):
                continue
            if record.install_id != binding.install_id or record.dataset_id != binding.dataset_id:
                continue
            if _RELEASE_ID_PATTERN.fullmatch(record.target_release_id):
                releases.add(record.target_release_id)
            if isinstance(record, UpgradeOperation) and _RELEASE_ID_PATTERN.fullmatch(record.previous_release_id):
                releases.add(record.previous_release_id)
        if exclude_release_id:
            excluded = exclude_release_id.casefold()
            releases = {rid for rid in releases if rid.casefold() != excluded}
        return frozenset(releases)

    @staticmethod
    def _operation_from_payload(payload: dict[str, object]) -> ActiveOperation | ConnectorOperation:
        return operation_from_payload(payload)

    def prepare(self, request: InstallRequest) -> None:
        self._adapters.security.prepare_operation_store(request)

    def require_fresh_inputs(self, request: InstallRequest) -> None:
        self._adapters.security.require_fresh_inputs(request)

    def publish_active(self, operation: ActiveOperation | ConnectorOperation) -> None:
        reject_reparse_components(self._active_path)
        reject_reparse_components(self._active_temp_path)
        if operation.phase != "committed" and self._active_path.exists():
            try:
                current = self.read_active()
            except (LifecycleError, OSError, ValueError) as exc:
                raise LifecycleError(
                    "active_state_unreadable",
                    "refusing to overwrite unreadable active operation with non-committed state",
                ) from exc
            if (
                current is not None
                and current.operation_id == operation.operation_id
                and current.phase == "committed"
            ):
                raise LifecycleViolation(
                    "committed_operation_immutable",
                    "refusing to overwrite a committed operation with non-committed state",
                )
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

    def archive_committed(self, operation: ActiveOperation | ConnectorOperation) -> None:
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
        if not os.path.lexists(self._binding_path):
            return None
        if not self._binding_path.is_file():
            raise LifecycleError(
                "machine_state_invalid",
                f"{self._binding_path.name} must be a regular file",
            )
        payload = self._read_verified_json(
            self._binding_path,
            self._adapters.security.verify_binding_json,
        )
        return binding_from_payload(payload)

    def publish(self, binding: InstallationBinding) -> None:
        reject_reparse_components(self._binding_path)
        self._machine_root.mkdir(parents=True, exist_ok=True)
        tmp_path = _write_temp_json(self._binding_path, asdict(binding))
        try:
            self._adapters.security.grant_backend_binding_read(
                tmp_path,
                binding.backend_service_name,
            )
            self._adapters.security.verify_binding_json(
                tmp_path,
                binding.backend_service_name,
            )
            os.replace(tmp_path, self._binding_path)
            self._adapters.security.verify_binding_json(
                self._binding_path,
                binding.backend_service_name,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _read_verified_json(
        self,
        path: Path,
        verifier: Callable[[Path, str], None],
    ) -> dict[str, object]:
        verifier(path, self._backend_service_name)
        text = path.read_text(encoding="utf-8")
        verifier(path, self._backend_service_name)
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
        if not isinstance(payload, dict):
            raise LifecycleError("machine_state_invalid", f"{path.name} must contain a JSON object")
        return payload
