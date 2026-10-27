from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain.install import (
    inspect_machine,
    install_or_resume,
)
from ticketbox_lifecycle.domain.operation import LifecycleStores
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.schemas import (
    RESULT_SCHEMA,
    ActiveOperation,
    CommandResult,
)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "connector":
        from ticketbox_lifecycle.connector_cli import main as connector_main

        return connector_main(argv)
    if argv and argv[0] == "restore":
        from ticketbox_lifecycle.restore_cli import main as restore_main

        return restore_main(argv)
    if argv and argv[0] in {"cold-copy", "verify-cold-copy"}:
        from ticketbox_lifecycle.cold_copy_cli import main as cold_main

        return cold_main(argv)
    return _install_main(argv)


def _install_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        epilog="Beta retention: cold-copy --output <new.tbxcold>; verify-cold-copy --source <copy.tbxcold>.",
    )
    parser.add_argument("command", choices=("install", "resume", "inspect"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    operation_id = "unknown"
    lifecycle_stores: LifecycleStores | None = None
    try:
        payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
        operation_id = str(payload.get("operation_id") or "unknown")
        command_io.write_result(
            result_path,
            CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command=args.command,
                operation_id=operation_id,
                phase="prepared",
                code="running",
                message="lifecycle started",
                installation_published=False,
            ),
        )
        request = command_io.parse_request(payload, command=args.command)
        operation_id = request.operation_id
        stores = FilesystemStores.from_request(request)
        lifecycle_stores = stores.as_lifecycle_stores()
        if args.command == "inspect":
            result = inspect_machine(lifecycle_stores, request)
        else:
            result = install_or_resume(lifecycle_stores, request)
    except LifecycleError as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=operation_id,
            phase="failed_recoverable",
            code=exc.code,
            message=exc.message,
            installation_published=False,
        )
    except Exception:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=operation_id,
            phase="failed_recoverable",
            code="unhandled",
            message="unexpected lifecycle failure",
            installation_published=False,
        )
    if args.command in {"install", "resume"} and lifecycle_stores is not None:
        return _deliver_install_result(result_path, result, lifecycle_stores)
    command_io.write_result(result_path, result)
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2


def _deliver_install_result(
    path: Path,
    result: CommandResult,
    stores: LifecycleStores,
) -> int:
    if not result.ok:
        command_io.write_result(path, result)
        command_io.emit_failure(result)
        return 2
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
        command_io.write_result(path, failure)
        command_io.emit_failure(failure)
        return 2
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
            command_io.write_result(path, failure)
            command_io.emit_failure(failure)
            return 2
    command_io.write_result(path, result)
    return 0


def _is_exact_commit(operation: ActiveOperation | None, operation_id: str) -> bool:
    return (
        operation is not None
        and operation.kind in {"install", "restore"}
        and operation.phase == "committed"
        and operation.operation_id == operation_id
    )


if __name__ == "__main__":
    raise SystemExit(main())
