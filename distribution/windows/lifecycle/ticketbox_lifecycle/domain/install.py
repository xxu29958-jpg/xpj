from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace

from ticketbox_lifecycle.adapters.ports import (
    AdapterBundle,
    BindingPublisher,
    BindingReader,
    HostObserver,
    Mutex,
    OperationPublisher,
    OperationReader,
    PlatformAdapter,
    ShipmentVerifier,
    adapter_for_step,
    phase_after,
)
from ticketbox_lifecycle.domain.binding import (
    ensure_runtime_binding,
    require_runtime_binding,
)
from ticketbox_lifecycle.domain.planner import plan_fresh_install
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    ActiveOperation,
    CommandResult,
    DurablePhase,
    InstallationBinding,
    InstallRequest,
    OwnerPairing,
)


@dataclass(frozen=True)
class LifecycleStores:
    mutex: Mutex
    shipment: ShipmentVerifier
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
    request = stores.shipment.bind_and_verify(request)
    existing = stores.operations_read.read_active()
    committed = (
        stores.operations_read.read_committed(request.operation_id)
        if existing is None
        else None
    )
    request_hash = hash_install_identity(request)
    binding = stores.binding_read.read()
    _refuse_second_identity(binding, request, existing, committed)
    if existing is not None:
        _require_matching_operation(existing, request, request_hash)
        if existing.phase == "committed":
            if request.command != "resume":
                raise LifecycleViolation("already_installed", "committed delivery requires resume")
            return _replay_committed_result(stores, request, existing)
    elif committed is not None:
        _require_matching_operation(committed, request, request_hash)
        if request.command != "resume":
            raise LifecycleViolation("already_installed", "committed delivery requires resume")
        return _replay_committed_result(stores, request, committed)

    active = existing
    bound = None if active is None else _bind_operation_identity(request, active)
    installation_published = binding is not None
    try:
        observation = stores.observer.observe(request)
        plan = plan_fresh_install(request, observation)
        if active is None:
            stores.operations_write.require_fresh_inputs(request)
        stores.operations_write.prepare(request)
        if active is None:
            candidate = ActiveOperation(
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
                schema_revision=request.schema_revision,
            )
            stores.operations_write.publish_active(candidate)
            active = candidate
        bound = _bind_operation_identity(request, active)
        last_phase: DurablePhase = active.phase
        owner_pairing: OwnerPairing | None = None
        for step in plan.steps:
            if step.name == "owner_claim":
                owner_pairing = stores.adapters.dataset.claim_owner(bound)
                result = "claimed"
            else:
                adapter = adapter_for_step(stores.adapters, step.name)
                result = _ensure_postcondition(adapter, bound, step.name)
            last_phase = phase_after(step.name)
            candidate = replace(
                active,
                phase=last_phase,
                no_return_point=last_phase in {"data_ready", "release_activated"},
                last_adapter_result=f"{step.name}:{result}",
            )
            stores.operations_write.publish_active(candidate)
            active = candidate

        if owner_pairing is None:
            raise LifecycleViolation("owner_pairing_missing", "owner claim returned no pairing")
        ensure_runtime_binding(stores.binding_read, stores.binding_write, bound)
        installation_published = True
        committed = replace(
            active,
            phase="committed",
            no_return_point=True,
        )
        stores.operations_write.publish_active(committed)
        active = committed
    except (LifecycleError, OSError) as exc:
        if active is None or bound is None:
            raise
        return _failed_operation_result(
            stores,
            request,
            active,
            bound,
            installation_published=installation_published,
            primary=exc,
        )
    try:
        stores.adapters.scm.enable_autostart(bound)
    except LifecycleError as exc:
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="committed",
            code=exc.code,
            message=exc.message,
            installation_published=True,
        )
    return _committed_result(request, owner_pairing)


def _failed_operation_result(
    stores: LifecycleStores,
    request: InstallRequest,
    active: ActiveOperation,
    bound: InstallRequest,
    *,
    installation_published: bool,
    primary: LifecycleError | OSError,
) -> CommandResult:
    code, message = _failure_identity(primary)
    try:
        stores.adapters.scm.fence_backend(bound)
    except (LifecycleError, OSError) as failure:
        message = _append_failure(message, "backend fence", failure)

    failed = replace(active, phase="failed_recoverable")
    try:
        stores.operations_write.publish_active(failed)
    except (LifecycleError, OSError) as failure:
        message = _append_failure(message, "failed-state publication", failure)
    else:
        active = failed

    if not installation_published:
        try:
            installation_published = stores.binding_read.read() is not None
        except (LifecycleError, OSError) as failure:
            message = _append_failure(message, "binding readback", failure)

    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=False,
        command=request.command,
        operation_id=request.operation_id,
        phase=active.phase,
        code=code,
        message=message,
        installation_published=installation_published,
    )


def _append_failure(
    message: str,
    subject: str,
    failure: LifecycleError | OSError,
) -> str:
    code, detail = _failure_identity(failure)
    return f"{message}; {subject} failed ({code}): {detail}"


def _failure_identity(failure: LifecycleError | OSError) -> tuple[str, str]:
    if isinstance(failure, LifecycleError):
        return failure.code, failure.message
    return "operation_io_failed", "lifecycle operation I/O failed"


def _require_matching_operation(
    active: ActiveOperation,
    request: InstallRequest,
    request_hash: str,
) -> None:
    if active.operation_id != request.operation_id:
        raise LifecycleViolation(
            "operation_conflict",
            "a different active operation owns the machine",
        )
    if active.request_hash != request_hash:
        raise LifecycleViolation(
            "request_mismatch",
            "resume requires the same immutable request hash",
        )
    if active.target_release_id != request.target_release_id:
        raise LifecycleViolation(
            "release_mismatch",
            "resume requires the same target release",
        )


def _bind_operation_identity(
    request: InstallRequest,
    active: ActiveOperation,
) -> InstallRequest:
    return replace(
        request,
        install_id=active.install_id,
        dataset_id=active.dataset_id,
        schema_revision=active.schema_revision or request.schema_revision,
        schema_min_compatible=request.schema_min_compatible,
        semantic_revision=request.semantic_revision,
    )


def _replay_committed_result(
    stores: LifecycleStores,
    request: InstallRequest,
    active: ActiveOperation,
) -> CommandResult:
    bound = _bind_operation_identity(request, active)
    require_runtime_binding(stores.binding_read, bound)
    try:
        stores.adapters.scm.enable_autostart(bound)
        _ensure_postcondition(stores.adapters.scm, bound, "start_services")
        pairing = stores.adapters.dataset.claim_owner(bound)
        _ensure_postcondition(stores.adapters.dataset, bound, "health")
    except LifecycleError as exc:
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=request.command,
            operation_id=request.operation_id,
            phase="committed",
            code=exc.code,
            message=exc.message,
            installation_published=True,
        )
    return _committed_result(request, pairing)


def _ensure_postcondition(
    adapter: PlatformAdapter,
    request: InstallRequest,
    step: str,
) -> str:
    try:
        adapter.verify(request, step)
        return "already-verified"
    except LifecycleError as exc:
        if exc.code in {"command_outcome_unknown", "command_start_failed"}:
            raise
    result = adapter.apply(request, step)
    adapter.verify(request, step)
    return result


def _committed_result(request: InstallRequest, pairing: OwnerPairing) -> CommandResult:
    return CommandResult(
        schema=RESULT_SCHEMA,
        ok=True,
        command=request.command,
        operation_id=request.operation_id,
        phase="committed",
        code="committed",
        message="fresh install committed",
        installation_published=True,
        pairing_code=pairing.pairing_code,
        pairing_expires_at=pairing.pairing_expires_at,
    )


def _refuse_second_identity(
    binding: InstallationBinding | None,
    request: InstallRequest,
    active: ActiveOperation | None,
    committed: ActiveOperation | None,
) -> None:
    if binding is None:
        return
    operation = active or committed
    same_operation = (
        operation is not None
        and operation.operation_id == request.operation_id
        and binding.install_id == operation.install_id
        and binding.dataset_id == operation.dataset_id
        and binding.active_release_id == operation.target_release_id
        and binding.release_manifest_sha256 == operation.release_manifest_sha256
    )
    if not same_operation:
        raise LifecycleViolation(
            "already_installed",
            "installation.json already exists; refusing a second dataset identity",
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
