"""Shared operation stores and failure fencing for the supported install and R1 actions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ticketbox_lifecycle.adapters.ports import (
    AdapterBundle,
    BindingPublisher,
    BindingReader,
    HostObserver,
    Mutex,
    OperationPublisher,
    OperationReader,
    ShipmentVerifier,
)
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import (
    RESULT_SCHEMA,
    ActiveOperation,
    CommandResult,
    InstallRequest,
    RestoreOperation,
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


def failed_operation_result(
    stores: LifecycleStores,
    request: InstallRequest,
    active: ActiveOperation | RestoreOperation,
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


def finalize_install_result(
    result: CommandResult,
    stores: LifecycleStores,
) -> CommandResult:
    if not result.ok:
        return result
    active = stores.operations_read.read_active()
    committed = (
        stores.operations_read.read_committed(result.operation_id)
        if active is None
        else None
    )
    if (
        result.phase != "committed"
        or (
            not _is_exact_commit(active, result.operation_id)
            and not _is_exact_commit(committed, result.operation_id)
        )
    ):
        failure = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=result.command,
            operation_id=result.operation_id,
            phase="committed",
            code="committed_operation_missing",
            message="committed result has no exact active operation",
            installation_published=result.installation_published,
        )
        return failure
    if _is_exact_commit(active, result.operation_id):
        try:
            stores.operations_write.archive_committed(active)
        except Exception as exc:
            failure = CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command=result.command,
                operation_id=result.operation_id,
                phase="committed",
                code="operation_archive_failed",
                message=str(exc),
                installation_published=result.installation_published,
            )
            return failure
    return result


def _is_exact_commit(operation: ActiveOperation | None, operation_id: str) -> bool:
    return (
        operation is not None
        and operation.kind in {"install", "restore"}
        and operation.phase == "committed"
        and operation.operation_id == operation_id
    )
