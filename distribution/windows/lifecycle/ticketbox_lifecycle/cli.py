from __future__ import annotations

import argparse
import json
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
    request_path = Path(args.request)
    result_path = Path(args.result)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    request = _parse_request(payload, command=args.command)
    stores = FilesystemStores.from_request(request)
    try:
        if args.command == "inspect":
            result = inspect_machine(stores.as_lifecycle_stores(), request)
        else:
            result = install_or_resume(stores.as_lifecycle_stores(), request)
    except LifecycleError as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=request.operation_id,
            phase="failed_recoverable",
            code=exc.code,
            message=exc.message,
            installation_published=False,
        )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8")
    return 0 if result.ok else 2


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
