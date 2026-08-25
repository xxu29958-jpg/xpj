from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle.domain.install import LifecycleStores, inspect_machine, install_or_resume
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, RESULT_SCHEMA, CommandResult, InstallRequest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="TicketboxLifecycle")
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
        _write_result(
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
        request = _parse_request(payload, command=args.command)
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
    except Exception as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=operation_id,
            phase="failed_recoverable",
            code="unhandled",
            message=str(exc),
            installation_published=False,
        )
    if args.command in {"install", "resume"} and lifecycle_stores is not None:
        return _deliver_install_result(result_path, result, lifecycle_stores)
    _write_result(result_path, result)
    return 0 if result.ok else 2


def _deliver_install_result(
    path: Path,
    result: CommandResult,
    stores: LifecycleStores,
) -> int:
    _write_result(path, result)
    if not result.ok:
        return 2
    active = stores.operations_read.read_active()
    if (
        result.phase != "committed"
        or active is None
        or active.phase != "committed"
        or active.operation_id != result.operation_id
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
        _write_result(path, failure)
        return 2
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
        _write_result(path, failure)
        return 2
    return 0


def _write_result(path: Path, result: CommandResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(result), indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _parse_request(payload: dict[str, object], *, command: str) -> InstallRequest:
    if payload.get("schema") != REQUEST_SCHEMA:
        raise LifecycleError("bad_request_schema", "request schema is not ticketbox-lifecycle-request-v1")
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command=command,  # type: ignore[arg-type]
        operation_id=str(payload["operation_id"]),
        request_hash=str(payload["request_hash"]),
        target_release_id=str(payload["target_release_id"]),
        app_dir=str(payload["app_dir"]),
        data_root=str(payload["data_root"]),
        program_data_root=str(payload["program_data_root"]),
        pg_service_name=str(payload["pg_service_name"]),
        backend_service_name=str(payload["backend_service_name"]),
        pg_port=int(payload["pg_port"]),
        backend_port=int(payload["backend_port"]),
        postgres_major=int(payload["postgres_major"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
    )


if __name__ == "__main__":
    raise SystemExit(main())
