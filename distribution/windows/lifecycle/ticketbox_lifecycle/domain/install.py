from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from ticketbox_lifecycle.adapters.ports import (
    AdapterBundle,
    BindingPublisher,
    BindingReader,
    HostObserver,
    Mutex,
    OperationPublisher,
    OperationReader,
    adapter_for_step,
    phase_after,
)
from ticketbox_lifecycle.domain.planner import plan_fresh_install
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    ActiveOperation,
    CommandResult,
    DurablePhase,
    InstallationBinding,
    InstallRequest,
)


@dataclass(frozen=True)
class LifecycleStores:
    mutex: Mutex
    observer: HostObserver
    operations_read: OperationReader
    operations_write: OperationPublisher
    binding_read: BindingReader
    binding_write: BindingPublisher
    adapters: AdapterBundle


def inspect_machine(stores: LifecycleStores, request: InstallRequest) -> CommandResult:
    observation = stores.observer.observe(request)
    binding = stores.binding_read.read()
    active = stores.operations_read.read_active()
    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command="inspect",
        operation_id=request.operation_id,
        phase=active.phase if active is not None else "prepared",
        code="inspected",
        message=(
            "installation="
            f"{binding.install_id if binding else 'none'}; "
            f"active={active.operation_id if active else 'none'}; "
            f"files={observation.program_files_present}"
        ),
        installation_published=binding is not None,
    )


def install_or_resume(stores: LifecycleStores, request: InstallRequest) -> CommandResult:
    stores.mutex.acquire()
    try:
        return _install_locked(stores, request)
    finally:
        stores.mutex.release()


def _install_locked(stores: LifecycleStores, request: InstallRequest) -> CommandResult:
    if stores.binding_read.read() is not None and request.command == "install":
        raise LifecycleViolation(
            "already_installed",
            "installation.json already exists; refusing a second dataset identity",
        )
    observation = stores.observer.observe(request)
    plan = plan_fresh_install(request, observation)
    existing = stores.operations_read.read_active()
    if existing is None:
        schema_revision = request.schema_revision or _schema_revision_from_release(request)
        active = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=request.operation_id,
            kind="install",
            request_hash=request.request_hash,
            target_release_id=request.target_release_id,
            phase="prepared",
            no_return_point=False,
            last_adapter_result=None,
            install_id=request.install_id or str(uuid.uuid4()),
            dataset_id=request.dataset_id or str(uuid.uuid4()),
            schema_revision=schema_revision,
        )
        stores.operations_write.publish_active(active)
    else:
        if existing.request_hash != request.request_hash:
            raise LifecycleViolation(
                "request_mismatch",
                "resume requires the same immutable request hash",
            )
        active = existing
        if active.phase == "committed":
            raise LifecycleViolation("already_committed", "operation already committed")

    try:
        last_phase: DurablePhase = active.phase
        bound = replace(
            request,
            install_id=active.install_id,
            dataset_id=active.dataset_id,
            schema_revision=active.schema_revision or request.schema_revision,
            schema_min_compatible=request.schema_min_compatible or request.target_release_id,
            semantic_revision=request.semantic_revision or "ticketbox-dataset-semantics-v1",
        )
        for step in plan.steps:
            adapter = adapter_for_step(stores.adapters, step.name)
            try:
                adapter.verify(bound, step.name)
                result = "already-verified"
            except LifecycleError:
                result = adapter.apply(bound, step.name)
                adapter.verify(bound, step.name)
            last_phase = phase_after(step.name)
            active = ActiveOperation(
                schema=OPERATION_SCHEMA,
                operation_id=active.operation_id,
                kind=active.kind,
                request_hash=active.request_hash,
                target_release_id=active.target_release_id,
                phase=last_phase,
                no_return_point=last_phase in {"data_ready", "release_activated"},
                last_adapter_result=f"{step.name}:{result}",
                install_id=active.install_id,
                dataset_id=active.dataset_id,
                schema_revision=active.schema_revision,
            )
            stores.operations_write.publish_active(active)

        binding = _binding_from_request(bound)
        stores.binding_write.publish(binding)
        committed = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=active.operation_id,
            kind=active.kind,
            request_hash=active.request_hash,
            target_release_id=active.target_release_id,
            phase="committed",
            no_return_point=True,
            last_adapter_result=active.last_adapter_result,
            install_id=active.install_id,
            dataset_id=active.dataset_id,
            schema_revision=active.schema_revision,
        )
        stores.operations_write.archive_committed(committed)
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=True,
            command=request.command,
            operation_id=request.operation_id,
            phase="committed",
            code="committed",
            message="fresh install committed",
            installation_published=True,
        )
    except LifecycleError as exc:
        failed = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=active.operation_id,
            kind=active.kind,
            request_hash=active.request_hash,
            target_release_id=active.target_release_id,
            phase="failed_recoverable",
            no_return_point=active.no_return_point,
            last_adapter_result=active.last_adapter_result,
            install_id=active.install_id,
            dataset_id=active.dataset_id,
            schema_revision=active.schema_revision,
        )
        stores.operations_write.publish_active(failed)
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="failed_recoverable",
            code=exc.code,
            message=exc.message,
            installation_published=stores.binding_read.read() is not None,
        )


def _binding_from_request(request: InstallRequest) -> InstallationBinding:
    if not request.install_id or not request.dataset_id:
        raise LifecycleViolation("missing_identity", "install_id and dataset_id must be bound before publication")
    return InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=request.install_id,
        dataset_id=request.dataset_id,
        expected_restore_epoch=0,
        data_root=request.data_root,
        active_release_id=request.target_release_id,
        previous_release_id=None,
        release_manifest_sha256=request.release_manifest_sha256,
        postgres_major=request.postgres_major,
        pg_service_name=request.pg_service_name,
        backend_service_name=request.backend_service_name,
        pg_port=request.pg_port,
        backend_port=request.backend_port,
    )


def hash_request_payload(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _read_release_manifest(request: InstallRequest) -> dict[str, object]:
    path = (
        Path(request.app_dir)
        / "releases"
        / request.target_release_id
        / "release-manifest.json"
    )
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_revision_from_release(request: InstallRequest) -> str:
    if request.schema_revision:
        return request.schema_revision
    manifest = _read_release_manifest(request)
    return str(manifest.get("max_schema_revision") or "")


def _schema_min_from_release(request: InstallRequest) -> str:
    if request.schema_min_compatible:
        return request.schema_min_compatible
    manifest = _read_release_manifest(request)
    return str(manifest.get("min_schema_revision") or "")
