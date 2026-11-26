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
from ticketbox_lifecycle.domain.operation import LifecycleStores, finalize_install_result
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.schemas import (
    RESULT_SCHEMA,
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
    if argv and argv[0] in {"upgrade", "rollback-upgrade"}:
        from ticketbox_lifecycle.upgrade_cli import main as upgrade_main

        return upgrade_main(argv)
    if argv and argv[0] == "uninstall":
        from ticketbox_lifecycle.uninstall_cli import main as uninstall_main

        return uninstall_main(argv)
    if argv and argv[0] == "reinstall":
        from ticketbox_lifecycle.reinstall_cli import main as reinstall_main

        return reinstall_main(argv)
    if argv and argv[0] == "purge-data":
        from ticketbox_lifecycle.purge_data_cli import main as purge_main

        return purge_main(argv)
    if argv and argv[0] in {"cold-copy", "verify-cold-copy", "encrypt-cold-copy", "decrypt-cold-copy", "verify-encrypted-cold-copy"}:
        from ticketbox_lifecycle.cold_copy_cli import main as cold_main

        return cold_main(argv)
    return _install_main(argv)


def _install_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        epilog="Retention commands: cold-copy, verify-cold-copy, encrypt-cold-copy, decrypt-cold-copy, verify-encrypted-cold-copy. Use <command> --help.",
    )
    parser.add_argument("command", choices=("install", "resume", "inspect"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    operation_id = "unknown"
    lifecycle_stores: LifecycleStores | None = None
    forbidden_roots: list[Path] = []
    forbidden_roots_ready = False
    result_path_safe = False
    try:
        expected_app_dir, expected_program_data, forbidden_roots = command_io.resolve_default_forbidden_roots(
            install_root_fn=ticketbox_install_root,
            program_data_root_fn=ticketbox_program_data_root,
            allow_non_windows=True,
        )
        forbidden_roots_ready = True
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
        operation_id = str(payload.get("operation_id") or "unknown")
        request = command_io.parse_request(payload, command=args.command)
        operation_id = request.operation_id
        forbidden_roots.extend([Path(request.app_dir), Path(request.program_data_root), Path(request.data_root)])
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        result_path_safe = True
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
        stores = FilesystemStores.from_request(request)
        if isinstance(stores, FilesystemStores):
            lifecycle_stores = stores.as_lifecycle_stores(
                install_root=expected_app_dir,
                program_data_root=expected_program_data,
            )
        else:
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
        result = finalize_install_result(result, lifecycle_stores)
    if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
        command_io.write_result_if_safe(result_path, result, forbidden_roots=forbidden_roots)
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
