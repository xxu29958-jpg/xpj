from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from ticketbox_lifecycle.domain.install import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    APPLY_SEQUENCE,
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    ActiveOperation,
    HostObservation,
    InstallationBinding,
    InstallRequest,
    OwnerPairing,
)


class MemoryMutex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquired = 0

    def acquire(self) -> None:
        self._lock.acquire()
        self.acquired += 1

    def release(self) -> None:
        self._lock.release()


class _StatefulAdapter:
    def __init__(self, name: str, steps: tuple[str, ...]) -> None:
        self.name = name
        self._steps = set(steps)
        self.applied: list[str] = []
        self.fail_on: str | None = None
        self.apply_calls = 0
        self.verify_calls = 0
        self._done: set[str] = set()

    def apply(self, request: InstallRequest, step: str) -> str:
        self.apply_calls += 1
        if not request.app_dir:
            raise LifecycleViolation("ambient_forbidden", "adapter received empty app_dir")
        if step not in self._steps:
            raise LifecycleViolation("wrong_adapter", f"{self.name} cannot apply {step}")
        if self.fail_on == step:
            raise LifecycleError("injected_failure", f"forced failure at {step}")
        self.applied.append(step)
        self._done.add(step)
        Path(request.program_data_root).mkdir(parents=True, exist_ok=True)
        return "applied"

    def verify(self, request: InstallRequest, step: str) -> None:
        self.verify_calls += 1
        if step not in self._steps:
            raise LifecycleViolation("wrong_adapter", f"{self.name} cannot verify {step}")
        if step not in self._done:
            raise LifecycleError("postcondition_missing", f"{step} postcondition is absent")

    def claim_owner(self, request: InstallRequest) -> OwnerPairing:
        self.apply(request, "owner_claim")
        return OwnerPairing(
            pairing_code="12345678",
            pairing_expires_at="2026-08-25T12:00:00Z",
        )


class _RecordingScmAdapter(_StatefulAdapter):
    def __init__(self) -> None:
        super().__init__("scm", ("scm", "start_services"))
        self.autostart_enabled = False
        self.autostart_calls = 0
        self.fail_autostart = False

    def enable_autostart(self, request: InstallRequest) -> None:
        self.autostart_calls += 1
        if not request.install_id or not request.dataset_id:
            raise LifecycleViolation("identity_missing", "autostart requires bound identity")
        if self.fail_autostart:
            raise LifecycleError("injected_autostart_failure", "forced autostart failure")
        self.autostart_enabled = True


class RecordingAdapterBundle:
    def __init__(self) -> None:
        self.files = _StatefulAdapter("files", ("programdata_root",))
        self.security = _StatefulAdapter("security", ("acl",))
        self.postgres = _StatefulAdapter("postgres", ("postgres_initdb", "start_postgres", "roles_database"))
        self.alembic = _StatefulAdapter("alembic", ("alembic",))
        self.scm = _RecordingScmAdapter()
        self.dataset = _StatefulAdapter("dataset", ("owner_claim", "health"))

    def apply_order(self) -> list[str]:
        return [step for step in APPLY_SEQUENCE if any(
            step in adapter.applied
            for adapter in (
                self.files,
                self.security,
                self.postgres,
                self.alembic,
                self.scm,
                self.dataset,
            )
        )]


class MemoryStores:
    def __init__(self, adapters: RecordingAdapterBundle, app_dir: str, data_root: str) -> None:
        self.mutex = MemoryMutex()
        self.adapters = adapters
        self._app_dir = app_dir
        self._data_root = data_root
        self._active: ActiveOperation | None = None
        self._history: list[ActiveOperation] = []
        self._binding: InstallationBinding | None = None
        self.binding_publish_count = 0
        self.operation_store_prepared = False
        self.fresh_inputs_check_count = 0
        self.reject_fresh_inputs = False

    def as_lifecycle_stores(self) -> LifecycleStores:
        return LifecycleStores(
            mutex=self.mutex,
            shipment=self,
            observer=self,
            operations_read=self,
            operations_write=self,
            binding_read=self,
            binding_write=self,
            adapters=self.adapters,
        )

    def observe(self, request: InstallRequest) -> HostObservation:
        return HostObservation(
            installation_present=self._binding is not None,
            active_operation_present=self._active is not None,
            active_operation_id=None if self._active is None else self._active.operation_id,
            active_phase=None if self._active is None else self._active.phase,
            program_files_present=Path(self._app_dir).exists(),
            data_root_present=Path(self._data_root).exists(),
        )

    def read_active(self) -> ActiveOperation | None:
        return self._active

    def read_committed(self, operation_id: str) -> ActiveOperation | None:
        matches = [item for item in self._history if item.operation_id == operation_id]
        return matches[-1] if matches else None

    def bind_and_verify(self, request: InstallRequest) -> InstallRequest:
        manifest_path = (
            Path(request.app_dir)
            / "releases"
            / request.target_release_id
            / "release-manifest.json"
        )
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != request.release_manifest_sha256:
            raise LifecycleViolation(
                "release_hash_mismatch",
                "installed release manifest does not match this Setup request",
            )
        manifest = json.loads(manifest_bytes)
        return InstallRequest(
            **{
                **request.__dict__,
                "schema_revision": str(manifest.get("max_schema_revision") or ""),
                "schema_min_compatible": str(manifest.get("product_version") or ""),
                "semantic_revision": str(manifest.get("min_semantic_revision") or ""),
            }
        )

    def prepare(self, request: InstallRequest) -> None:
        del request
        self.operation_store_prepared = True

    def require_fresh_inputs(self, request: InstallRequest) -> None:
        del request
        self.fresh_inputs_check_count += 1
        if self.reject_fresh_inputs:
            raise LifecycleViolation(
                "preexisting_mutable_state",
                "fresh install refuses unbound mutable state",
            )

    def publish_active(self, operation: ActiveOperation) -> None:
        assert self.operation_store_prepared
        if operation.schema != OPERATION_SCHEMA:
            raise LifecycleViolation("bad_operation_schema", "active operation schema")
        self._active = operation

    def archive_committed(self, operation: ActiveOperation) -> None:
        if operation.phase != "committed":
            raise LifecycleViolation("archive_requires_commit", "history cannot keep mutation authority")
        self._history.append(operation)
        self._active = None

    def read(self) -> InstallationBinding | None:
        return self._binding

    def publish(self, binding: InstallationBinding) -> None:
        if binding.schema != INSTALLATION_SCHEMA:
            raise LifecycleViolation("bad_binding_schema", "installation schema")
        if self._binding is not None:
            raise LifecycleViolation("second_writer", "installation.json publisher must be unique")
        self._binding = binding
        self.binding_publish_count += 1

    @property
    def history(self) -> list[ActiveOperation]:
        return list(self._history)
