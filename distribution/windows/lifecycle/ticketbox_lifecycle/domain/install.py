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
    _refuse_second_identity(stores, request)
    request = _bind_release_manifest_hash(request)
    observation = stores.observer.observe(request)
    plan = plan_fresh_install(request, observation)
    stores.operations_write.prepare(request)
    existing = stores.operations_read.read_active()
    request_hash = hash_install_identity(request)
    if existing is None:
        stores.operations_write.require_fresh_inputs(request)
        schema_revision = request.schema_revision or _schema_revision_from_release(request)
        active = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=request.operation_id,
            kind="install",
            request_hash=request_hash,
            target_release_id=request.target_release_id,
            data_root=request.data_root,
            release_manifest_sha256=request.release_manifest_sha256,
            backend_port=request.backend_port,
            phase="prepared",
            no_return_point=False,
            last_adapter_result=None,
            install_id=request.install_id or str(uuid.uuid4()),
            dataset_id=request.dataset_id or str(uuid.uuid4()),
            schema_revision=schema_revision,
        )
        stores.operations_write.publish_active(active)
    else:
        if existing.operation_id != request.operation_id:
            raise LifecycleViolation(
                "operation_mismatch",
                "resume requires the same operation_id",
            )
        if existing.request_hash != request_hash:
            raise LifecycleViolation(
                "request_mismatch",
                "resume requires the same immutable request hash",
            )
        if existing.target_release_id != request.target_release_id:
            raise LifecycleViolation(
                "release_mismatch",
                "resume requires the same target release",
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
        owner_pairing = None
        for step in plan.steps:
            if step.name == "owner_claim":
                owner_pairing = stores.adapters.dataset.claim_owner(bound)
                result = "claimed"
            else:
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
                data_root=active.data_root,
                release_manifest_sha256=active.release_manifest_sha256,
                backend_port=active.backend_port,
                phase=last_phase,
                no_return_point=last_phase in {"data_ready", "release_activated"},
                last_adapter_result=f"{step.name}:{result}",
                install_id=active.install_id,
                dataset_id=active.dataset_id,
                schema_revision=active.schema_revision,
            )
            stores.operations_write.publish_active(active)

        _ensure_runtime_binding(stores, bound)
        committed = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=active.operation_id,
            kind=active.kind,
            request_hash=active.request_hash,
            target_release_id=active.target_release_id,
            data_root=active.data_root,
            release_manifest_sha256=active.release_manifest_sha256,
            backend_port=active.backend_port,
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
            pairing_code=owner_pairing.pairing_code if owner_pairing is not None else "",
            pairing_expires_at=(
                owner_pairing.pairing_expires_at if owner_pairing is not None else ""
            ),
        )
    except LifecycleError as exc:
        failed = ActiveOperation(
            schema=OPERATION_SCHEMA,
            operation_id=active.operation_id,
            kind=active.kind,
            request_hash=active.request_hash,
            target_release_id=active.target_release_id,
            data_root=active.data_root,
            release_manifest_sha256=active.release_manifest_sha256,
            backend_port=active.backend_port,
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


def _refuse_second_identity(stores: LifecycleStores, request: InstallRequest) -> None:
    binding = stores.binding_read.read()
    if binding is None:
        return
    active = stores.operations_read.read_active()
    same_operation = (
        active is not None
        and active.operation_id == request.operation_id
        and binding.install_id == active.install_id
        and binding.dataset_id == active.dataset_id
    )
    if not same_operation:
        raise LifecycleViolation(
            "already_installed",
            "installation.json already exists; refusing a second dataset identity",
        )


def _ensure_runtime_binding(stores: LifecycleStores, request: InstallRequest) -> None:
    expected = _binding_from_request(request)
    current = stores.binding_read.read()
    if current is None:
        stores.binding_write.publish(expected)
        return
    if (
        current.install_id != expected.install_id
        or current.dataset_id != expected.dataset_id
        or current.data_root != expected.data_root
        or current.active_release_id != expected.active_release_id
        or current.release_manifest_sha256 != expected.release_manifest_sha256
    ):
        raise LifecycleViolation(
            "identity_conflict",
            "installation.json does not match this operation's runtime selector",
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


def hash_install_identity(request: InstallRequest) -> str:
    return hash_request_payload(
        {
            "target_release_id": request.target_release_id,
            "release_manifest_sha256": request.release_manifest_sha256,
            "app_dir": request.app_dir,
            "data_root": request.data_root,
            "program_data_root": request.program_data_root,
            "pg_service_name": request.pg_service_name,
            "backend_service_name": request.backend_service_name,
            "pg_port": request.pg_port,
            "backend_port": request.backend_port,
            "postgres_major": request.postgres_major,
        }
    )


def _release_manifest_path(request: InstallRequest) -> Path:
    return (
        Path(request.app_dir)
        / "releases"
        / request.target_release_id
        / "release-manifest.json"
    )


def _bind_release_manifest_hash(request: InstallRequest) -> InstallRequest:
    path = _release_manifest_path(request)
    if not path.is_file() or path.is_symlink():
        raise LifecycleViolation("missing_release_manifest", "installed release-manifest.json is absent")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    declared = request.release_manifest_sha256.strip().lower()
    if declared in {"", "pending"} or declared != actual:
        raise LifecycleViolation(
            "release_hash_mismatch",
            "installed release-manifest.json does not match the request hash",
        )
    return replace(request, release_manifest_sha256=actual)


def _read_release_manifest(request: InstallRequest) -> dict[str, object]:
    path = _release_manifest_path(request)
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
