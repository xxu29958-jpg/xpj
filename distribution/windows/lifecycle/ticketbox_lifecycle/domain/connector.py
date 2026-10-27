"""One finite connector-only transaction under the existing machine lease.

Public probes deliberately run after this function releases the lease. A host
commit is not a public-identity or boundary qualification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Protocol

from ticketbox_lifecycle.adapters.ports import BindingReader, Mutex, OperationPublisher, OperationReader
from ticketbox_lifecycle.connector_schema import (
    OPERATION_SCHEMA,
    PROFILE,
    STATE_SCHEMA,
    ConnectorOperation,
    ConnectorRequest,
    ConnectorState,
    parse_state,
    require_binding,
)
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation


class ConnectorStateStore(Protocol):
    def read(self) -> ConnectorState | None: ...
    def publish(self, state: ConnectorState) -> None: ...


class ConnectorHost(Protocol):
    def verify_context(self, request: ConnectorRequest) -> None: ...
    def verify_owned(self, request: ConnectorRequest, state: ConnectorState | None) -> None: ...
    def credential_identity(self, request: ConnectorRequest, generation: int, token: str | None) -> str: ...
    def prepare_credential(self, request: ConnectorRequest, generation: int, token: str | None) -> None: ...
    def prepare_service(self, request: ConnectorRequest, state: ConnectorState) -> None: ...
    def apply_desired(self, request: ConnectorRequest, state: ConnectorState) -> None: ...
    def verify_desired(self, request: ConnectorRequest, state: ConnectorState) -> None: ...
    def clean_credentials(self, request: ConnectorRequest, state: ConnectorState) -> None: ...


@dataclass(frozen=True)
class ConnectorStores:
    mutex: Mutex
    binding: BindingReader
    operations: OperationReader | OperationPublisher
    state: ConnectorStateStore
    host: ConnectorHost


def requires_configuration_token(stores: ConnectorStores, request: ConnectorRequest) -> bool:
    if request.action != "configure":
        return False
    active = stores.operations.read_active()
    if active is None and stores.operations.read_committed(request.operation_id) is not None:
        return False
    if isinstance(active, ConnectorOperation) and active.request_hash == request.request_hash and active.phase == "committed":
        return False
    if isinstance(active, ConnectorOperation) and active.request_hash == request.request_hash:
        try:
            stores.host.credential_identity(request, request.expected_credential_generation + 1, None)
            return False
        except LifecycleError as exc:
            if exc.code not in {"connector_credential_missing", "connector_token_invalid"}:
                raise
    return True


def run_connector(stores: ConnectorStores, request: ConnectorRequest, *, token: str | None = None) -> ConnectorOperation:
    stores.mutex.acquire()
    try:
        return _run_locked(stores, request, token)
    finally:
        stores.mutex.release()


def _run_locked(stores: ConnectorStores, request: ConnectorRequest, token: str | None) -> ConnectorOperation:
    require_binding(request, stores.binding.read())
    operation, previous = _existing_operation(stores, request)
    if operation is not None and operation.phase == "committed":
        # Lost response: replay the historical host result, never reapply it.
        # Observed state and public qualification are separately refreshed.
        if stores.operations.read_active() == operation:
            stores.operations.archive_committed(operation)
        return operation
    state = stores.state.read()
    target = _target(request, state.tunnel_id if state else None, previous)
    _require_state(request, state, target, resuming=operation is not None)
    stores.host.verify_context(request)
    stores.host.verify_owned(request, state)
    if request.action == "configure":
        if operation is None and token is None:
            raise LifecycleError("connector_input_cancelled", "native credential input was cancelled; no host changes")
        target = _target(request, stores.host.credential_identity(request, target.credential_generation, token))
    parse_state(asdict(target))
    if operation is None:
        operation = ConnectorOperation(OPERATION_SCHEMA, "connector", "connector_only", request.operation_id,
            request.request_hash, request, "prepared", None, "running", previous)
        stores.operations.publish_active(operation)
    try:
        return _advance(stores, operation, target, token)
    except (LifecycleError, OSError) as exc:
        # Do not call install's failure path: it fences the local Backend.
        failed = replace(operation,
            phase="manual_intervention" if isinstance(exc, LifecycleViolation) else "failed_recoverable",
            result_code=exc.code if isinstance(exc, LifecycleError) else "connector_host_io_failed")
        latest = stores.operations.read_active()
        if isinstance(latest, ConnectorOperation) and latest.request_hash == request.request_hash:
            failed = replace(failed, completed_step=latest.completed_step)
        stores.operations.publish_active(failed)
        raise


def _existing_operation(stores: ConnectorStores, request: ConnectorRequest) -> tuple[ConnectorOperation | None, ConnectorOperation | None]:
    active = stores.operations.read_active()
    operation = active or stores.operations.read_committed(request.operation_id)
    if operation is None:
        if request.closing_operation_id is not None:
            raise LifecycleViolation("connector_close_changed", "the operation selected for closure is no longer active")
        return None, None
    if isinstance(active, ConnectorOperation) and (request.closing_operation_id, request.closing_request_hash) == (active.operation_id, active.request_hash):
        if active.phase == "committed" or active.request.action == "remove" or active.replaced_operation is not None:
            raise LifecycleViolation("connector_close_invalid", "this operation must finish its exact existing request")
        require_binding(active.request, stores.binding.read())
        return None, active
    if not isinstance(operation, ConnectorOperation) or operation.operation_id != request.operation_id:
        raise LifecycleViolation("lifecycle_busy", "another lifecycle operation owns the machine")
    if operation.request_hash != request.request_hash:
        raise LifecycleViolation("connector_request_changed", "retry requires the same immutable connector request")
    return operation, operation.replaced_operation


def _target(request: ConnectorRequest, tunnel_id: str | None, previous: ConnectorOperation | None = None) -> ConnectorState:
    generation = request.expected_credential_generation
    if previous is not None:
        generation = max(generation, previous.request.expected_credential_generation + int(previous.request.action == "configure"))
    return ConnectorState(STATE_SCHEMA, PROFILE, request.install_id, request.dataset_id,
        request.expected_restore_epoch, request.release_manifest_sha256,
        request.expected_revision + 1,
        generation + int(request.action in {"configure", "remove"}),
        request.expected_public_origin_revision, request.desired_enabled,
        request.action != "remove", request.operation_id, None if request.action == "remove" else tunnel_id)


def _require_state(request: ConnectorRequest, state: ConnectorState | None, target: ConnectorState, *, resuming: bool) -> None:
    if resuming and state == target:
        return
    observed = (state.revision, state.credential_generation, state.enabled) if state else (0, 0, False)
    if observed != (request.expected_revision, request.expected_credential_generation, request.expected_enabled):
        raise LifecycleViolation("connector_stale_request", "connector revision, generation or enabled intent changed")
    if state is not None and any(getattr(state, name) != getattr(request, name) for name in (
        "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
    )):
        raise LifecycleViolation("connector_binding_changed", "connector record belongs to another installation or generation")
    if request.action != "configure" and request.closing_operation_id is None and (state is None or not state.configured):
        raise LifecycleViolation("connector_not_configured", "configure a dedicated connector first")
    if request.action == "reconnect" and not request.expected_enabled:
        raise LifecycleViolation("connector_paused", "reconnect cannot override a later pause")


def _advance(stores: ConnectorStores, operation: ConnectorOperation, target: ConnectorState, token: str | None) -> ConnectorOperation:
    request = operation.request
    # Pause/removal intention is durable before SCM changes. Until exact stop
    # readback succeeds it is pending, never a claim that traffic has stopped.
    stopping = request.action in {"set_enabled", "remove"} and not target.enabled
    state = stores.state.read()
    if stopping and state != target:
        stores.state.publish(target)
        operation = _checkpoint(stores, operation, "intent_published")
    if request.action == "configure":
        stores.host.prepare_credential(request, target.credential_generation, token)
        if operation.completed_step is None:
            operation = _checkpoint(stores, operation, "credential_prepared")
    if operation.completed_step not in {"intent_published", "host_applied"} or stopping:
        stores.host.prepare_service(request, target)
        if not stopping:
            operation = _checkpoint(stores, operation, "service_prepared")
    require_binding(request, stores.binding.read())
    stores.host.verify_context(request)
    if stores.state.read() != target:
        stores.state.publish(target)
        operation = _checkpoint(stores, operation, "intent_published")
    stores.host.apply_desired(request, target)
    stores.host.verify_desired(request, target)
    operation = _checkpoint(stores, operation, "host_applied")
    stores.host.clean_credentials(request, target)
    committed = replace(operation, phase="committed", result_code="removed_remote_revocation_pending"
        if request.action == "remove" else "host_committed_public_unverified")
    stores.operations.publish_active(committed)
    stores.operations.archive_committed(committed)
    return committed


def _checkpoint(stores: ConnectorStores, operation: ConnectorOperation, step: str) -> ConnectorOperation:
    advanced = replace(operation, phase="applying", completed_step=step, result_code="running")
    stores.operations.publish_active(advanced)
    return advanced
