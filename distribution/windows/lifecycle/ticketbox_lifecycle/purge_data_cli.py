"""Standalone administrator CLI for explicit permanent deletion of verified local host data."""

from __future__ import annotations

import argparse
import ctypes
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain.purge_data import PurgeDataRequest, purge_data
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_purge_data import WindowsPurgeDataPlatform
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        description="Standalone permanent deletion of verified local Ticketbox host data (never touches external backups)",
    )
    parser.add_argument("command", choices=("purge-data",))
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--confirm-dataset-id", required=True)
    parser.add_argument(
        "--external-backups-status",
        choices=("preserved_outside", "none_confirmed"),
        required=True,
    )
    parser.add_argument("--confirm-permanent-delete", action="store_true", required=True)
    parser.add_argument("--result", default="")
    args = parser.parse_args(argv)
    operation_id = f"purge-{uuid.uuid4().hex[:16]}"
    result_path = Path(args.result) if args.result else None
    forbidden_roots: list[Path] = []
    forbidden_roots_ready = False
    result_path_safe = result_path is None
    try:
        require_windows()
        app_dir, program_data, forbidden_roots = command_io.resolve_default_forbidden_roots(
            install_root_fn=ticketbox_install_root,
            program_data_root_fn=ticketbox_program_data_root,
        )
        assert app_dir is not None and program_data is not None
        forbidden_roots_ready = True
        if result_path is not None:
            command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
            result_path_safe = True
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("purge_admin_required", "permanent data deletion requires an administrator")
        fs_stores = FilesystemStores.from_installed(
            install_root=app_dir,
            program_data_root=program_data,
        )
        stores = fs_stores.as_lifecycle_stores()
        request = PurgeDataRequest(
            operation_id=operation_id,
            dataset_id=args.dataset_id,
            confirm_dataset_id=args.confirm_dataset_id,
            external_backups_status=args.external_backups_status,
            confirm_permanent_delete=bool(args.confirm_permanent_delete),
            program_data_root=str(program_data),
        )
        platform = WindowsPurgeDataPlatform(
            SubprocessCommandRunner(),
            dataset=fs_stores._adapters.dataset,  # type: ignore[arg-type]
            app_dir=app_dir,
        )
        result = purge_data(stores, request, platform)
    except LifecycleError as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="purge-data",
            operation_id=operation_id,
            phase="failed_recoverable",
            code=exc.code,
            message=exc.message,
            installation_published=None,
        )
    except Exception:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="purge-data",
            operation_id=operation_id,
            phase="failed_recoverable",
            code="unhandled",
            message="unexpected permanent data deletion failure",
            installation_published=None,
        )
    if result_path is not None:
        if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
            if not command_io.write_result_if_safe(result_path, result, forbidden_roots=forbidden_roots):
                command_io.emit_failure(
                    CommandResult(
                        schema=RESULT_SCHEMA,
                        ok=False,
                        command="purge-data",
                        operation_id=operation_id,
                        phase="failed_recoverable",
                        code="unsafe_result_path",
                        message="refusing to write purge result to an unsafe or non-result destination",
                        installation_published=None,
                    )
                )
                return 2
    else:
        print(json.dumps(asdict(result), ensure_ascii=True))
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
