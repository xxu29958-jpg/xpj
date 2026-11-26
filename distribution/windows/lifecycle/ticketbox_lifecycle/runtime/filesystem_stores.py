from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, fields
from pathlib import Path
from typing import cast

from ticketbox_lifecycle.adapters.ports import AdapterBundle, Mutex
from ticketbox_lifecycle.connector_schema import ConnectorOperation, parse_operation, parse_state
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.mutex import os_mutex
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_control_root,
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_security_native import (
    reject_reparse_components,
)
from ticketbox_lifecycle.runtime.windows_services import service_registered
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import (
    APPLY_SEQUENCE,
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REINSTALL_SEQUENCE,
    UNINSTALL_SEQUENCE,
    UPGRADE_SEQUENCE,
    ActiveOperation,
    ApplyStepName,
    DurablePhase,
    HostObservation,
    InstallationBinding,
    InstallRequest,
    ReinstallOperation,
    RestoreOperation,
    UninstallOperation,
    UninstallStepName,
    UpgradeOperation,
    UpgradeStepName,
)

_ACTIVE_OPERATION_FIELDS = frozenset(field.name for field in fields(ActiveOperation))
_UPGRADE_EXTRA_FIELDS = frozenset({
    "expected_restore_epoch",
    "previous_release_id",
    "previous_release_manifest_sha256",
    "source_schema_revision",
    "backup_path",
    "backup_sha256",
    "business_writes_opened",
})
_INSTALLATION_BINDING_FIELDS = frozenset(field.name for field in fields(InstallationBinding))
_RELEASE_ID_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")


_OPERATION_CLASS_BY_KIND = {
    "install": ActiveOperation,
    "restore": RestoreOperation,
    "upgrade": UpgradeOperation,
    "reinstall": ReinstallOperation,
    "uninstall": UninstallOperation,
}


def _expected_operation_fields(kind: str) -> frozenset[str]:
    if kind in {"restore", "reinstall", "uninstall"}:
        return _ACTIVE_OPERATION_FIELDS | {"expected_restore_epoch"}
    if kind == "upgrade":
        return _ACTIVE_OPERATION_FIELDS | _UPGRADE_EXTRA_FIELDS
    return _ACTIVE_OPERATION_FIELDS


def _operation_type(payload: dict[str, object]):
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in _OPERATION_CLASS_BY_KIND:
        raise LifecycleError("bad_operation_kind", "operation kind is unsupported")
    if set(payload) != _expected_operation_fields(kind):
        raise LifecycleError("bad_operation_fields", "operation fields are not closed")
    if payload.get("schema") != OPERATION_SCHEMA:
        raise LifecycleError("bad_operation_schema", "operation schema is not v2")
    if kind == "restore":
        epoch = payload["expected_restore_epoch"]
        if type(epoch) is not int or epoch <= 0:
            raise LifecycleError("bad_restore_epoch", "restore operation requires a positive target epoch")
    elif kind in {"reinstall", "uninstall"}:
        epoch = payload["expected_restore_epoch"]
        if type(epoch) is not int or epoch < 0:
            raise LifecycleError("bad_operation_epoch", f"{kind} operation requires a non-negative restore epoch")
    elif kind == "upgrade":
        _validate_upgrade_payload(payload)
    return _OPERATION_CLASS_BY_KIND[kind], kind


def _validate_upgrade_previous_lineage(payload: dict[str, object]) -> None:
    previous = payload["previous_release_id"]
    if (
        not isinstance(previous, str)
        or _RELEASE_ID_PATTERN.fullmatch(previous) is None
        or previous == payload["target_release_id"]
    ):
        raise LifecycleError("bad_upgrade_previous_release", "upgrade previous_release_id is invalid")
    prev_manifest = payload["previous_release_manifest_sha256"]
    if (
        not isinstance(prev_manifest, str)
        or re.fullmatch(r"[0-9a-f]{64}", prev_manifest) is None
        or prev_manifest == payload["release_manifest_sha256"]
    ):
        raise LifecycleError(
            "bad_upgrade_previous_manifest",
            "upgrade previous_release_manifest_sha256 is invalid",
        )


def _validate_upgrade_payload(payload: dict[str, object]) -> None:
    epoch = payload["expected_restore_epoch"]
    if type(epoch) is not int or epoch < 0:
        raise LifecycleError("bad_upgrade_epoch", "upgrade operation requires a non-negative restore epoch")
    _validate_upgrade_previous_lineage(payload)
    source_rev = payload["source_schema_revision"]
    if not isinstance(source_rev, str) or not source_rev:
        raise LifecycleError("bad_upgrade_source_revision", "upgrade source_schema_revision is invalid")
    backup_path = payload["backup_path"]
    backup_sha = payload["backup_sha256"]
    if not isinstance(backup_path, str) or not isinstance(backup_sha, str):
        raise LifecycleError("bad_upgrade_backup", "upgrade backup metadata is invalid")
    if backup_sha and re.fullmatch(r"[0-9a-f]{64}", backup_sha) is None:
        raise LifecycleError("bad_upgrade_backup", "upgrade backup sha256 is invalid")
    if type(payload["business_writes_opened"]) is not bool:
        raise LifecycleError("bad_upgrade_writes_flag", "upgrade business_writes_opened must be a boolean")


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
        if payload.get("schema") == "ticketbox-lifecycle-operation-v3":
            return parse_operation(payload)
        operation_type, kind = _operation_type(payload)
        completed_step = payload.get("completed_step")
        valid_steps = {
            "upgrade": UPGRADE_SEQUENCE,
            "reinstall": REINSTALL_SEQUENCE,
            "uninstall": UNINSTALL_SEQUENCE,
        }.get(kind, APPLY_SEQUENCE)
        if completed_step is not None and completed_step not in valid_steps:
            raise LifecycleError("bad_operation_progress", "operation completed_step is invalid")
        health_attestation_key = str(payload.get("health_attestation_key") or "")
        if re.fullmatch(r"[0-9a-f]{64}", health_attestation_key) is None:
            raise LifecycleError("bad_operation_attestation", "operation health attestation key is invalid")
        extra: dict[str, object] = {}
        if kind in {"restore", "reinstall", "uninstall"}:
            extra["expected_restore_epoch"] = payload["expected_restore_epoch"]
        elif kind == "upgrade":
            extra = {
                "expected_restore_epoch": payload["expected_restore_epoch"],
                "previous_release_id": str(payload["previous_release_id"]),
                "previous_release_manifest_sha256": str(payload["previous_release_manifest_sha256"]),
                "source_schema_revision": str(payload["source_schema_revision"]),
                "backup_path": str(payload["backup_path"]),
                "backup_sha256": str(payload["backup_sha256"]),
                "business_writes_opened": bool(payload["business_writes_opened"]),
            }
        return operation_type(
            schema=OPERATION_SCHEMA,
            operation_id=str(payload["operation_id"]),
            kind=payload["kind"],
            request_hash=str(payload["request_hash"]),
            target_release_id=str(payload["target_release_id"]),
            data_root=str(payload["data_root"]),
            release_manifest_sha256=str(payload["release_manifest_sha256"]),
            backend_port=int(payload["backend_port"]),
            phase=cast(DurablePhase, payload["phase"]),
            no_return_point=bool(payload["no_return_point"]),
            completed_step=cast(ApplyStepName | UpgradeStepName | UninstallStepName | None, completed_step),
            install_id=str(payload.get("install_id") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            schema_revision=str(payload.get("schema_revision") or ""),
            health_attestation_key=health_attestation_key,
            **extra,
        )

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
        if payload.get("schema") != INSTALLATION_SCHEMA:
            raise LifecycleError("bad_binding_schema", "installation.json schema is not v1")
        if set(payload) != _INSTALLATION_BINDING_FIELDS:
            raise LifecycleError("bad_binding_fields", "installation.json fields are not closed")
        health_attestation_key = str(payload["health_attestation_key"])
        if re.fullmatch(r"[0-9a-f]{64}", health_attestation_key) is None:
            raise LifecycleError(
                "bad_binding_attestation",
                "installation.json health attestation key is invalid",
            )
        active_release_id = str(payload["active_release_id"])
        previous_release_id = payload.get("previous_release_id")
        if previous_release_id is not None and (
            not isinstance(previous_release_id, str)
            or _RELEASE_ID_PATTERN.fullmatch(previous_release_id) is None
            or previous_release_id == active_release_id
        ):
            raise LifecycleError(
                "bad_binding_previous_release",
                "installation.json previous_release_id is invalid",
            )
        return InstallationBinding(
            schema=INSTALLATION_SCHEMA,
            install_id=str(payload["install_id"]),
            dataset_id=str(payload["dataset_id"]),
            expected_restore_epoch=int(payload["expected_restore_epoch"]),
            data_root=str(payload["data_root"]),
            active_release_id=active_release_id,
            previous_release_id=previous_release_id,
            release_manifest_sha256=str(payload["release_manifest_sha256"]),
            postgres_major=int(payload["postgres_major"]),
            pg_service_name=str(payload["pg_service_name"]),
            backend_service_name=str(payload["backend_service_name"]),
            pg_port=int(payload["pg_port"]),
            backend_port=int(payload["backend_port"]),
            health_attestation_key=health_attestation_key,
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


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError(
                "machine_state_invalid",
                f"duplicate JSON key in machine state: {key}",
            )
        result[key] = value
    return result


def _connector_state_file_present(
    state_path: Path,
    *,
    binding: InstallationBinding | None,
    allowed_manifest_shas: frozenset[str],
    verify_state_file: Callable[[Path], None] | None,
) -> bool:
    try:
        reject_reparse_components(state_path)
        if not state_path.is_file():
            return True
        if verify_state_file is not None:
            verify_state_file(state_path)
        raw = state_path.read_bytes()
        if verify_state_file is not None:
            verify_state_file(state_path)
        if len(raw) > 8192:
            return True
        state = parse_state(
            json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
        )
    except (OSError, UnicodeError, ValueError, LifecycleError):
        return True
    if state.configured or state.enabled or state.tunnel_id is not None or binding is None:
        return True
    expected_shas = allowed_manifest_shas or frozenset({binding.release_manifest_sha256})
    return (
        state.install_id != binding.install_id
        or state.dataset_id != binding.dataset_id
        or state.expected_restore_epoch != binding.expected_restore_epoch
        or state.release_manifest_sha256 not in expected_shas
    )


def _managed_connector_present(
    machine_root: Path,
    *,
    binding: InstallationBinding | None = None,
    allowed_manifest_shas: frozenset[str] = frozenset(),
    verify_state_file: Callable[[Path], None] | None = None,
) -> bool:
    if service_registered(CONNECTOR_SERVICE_NAME):
        return True
    connectors_root = machine_root / "connectors"
    connector_dir = connectors_root / "cloudflare"
    try:
        reject_reparse_components(connectors_root)
        reject_reparse_components(connector_dir)
    except (OSError, LifecycleError):
        return True
    secrets_dir = connector_dir / "secrets"
    if os.path.lexists(secrets_dir):
        try:
            reject_reparse_components(secrets_dir)
            if not secrets_dir.is_dir() or any(secrets_dir.iterdir()):
                return True
        except (OSError, LifecycleError):
            return True
    state_path = connector_dir / "state.json"
    if os.path.lexists(state_path):
        return _connector_state_file_present(
            state_path,
            binding=binding,
            allowed_manifest_shas=allowed_manifest_shas,
            verify_state_file=verify_state_file,
        )
    return False


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
