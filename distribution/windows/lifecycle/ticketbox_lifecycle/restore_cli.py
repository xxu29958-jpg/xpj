"""Administrator-only R1/R2 controlled recovery entry, using the existing lifecycle authority and adapters."""

from __future__ import annotations

import argparse
import ctypes
import json
import zipfile
from pathlib import Path

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain import restore as restore_action
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_cold_restore import WindowsColdRestore
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        description="Controlled R1 (same-environment) or R2 (cross-machine) recovery into a clean isolated Windows installation",
    )
    parser.add_argument("command", choices=("restore",))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-isolated", action="store_true", required=True)
    parser.add_argument(
        "--restore-mode",
        choices=("same-environment", "cross-machine"),
        default="same-environment",
    )
    args = parser.parse_args(argv)
    operation_id = "unknown"
    result_path = Path(args.result)
    source = Path(args.source)
    forbidden_roots: list[Path] = []
    protected_files = [source]
    forbidden_roots_ready = False
    result_path_safe = False
    try:
        require_windows()
        expected_app_dir, expected_program_data, forbidden_roots = command_io.resolve_default_forbidden_roots(
            install_root_fn=ticketbox_install_root,
            program_data_root_fn=ticketbox_program_data_root,
        )
        assert expected_app_dir is not None and expected_program_data is not None
        forbidden_roots_ready = True
        command_io.require_safe_result_path(
            result_path,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("restore_admin_required", "controlled recovery requires an administrator")
        if not source.is_absolute() or source.drive.startswith("\\\\") or source.suffix.lower() != ".tbxcold":
            raise LifecycleError("restore_source_invalid", "select an absolute local cold-copy file")
        request = command_io.parse_request(json.loads(Path(args.request).read_text(encoding="utf-8")), command="restore")
        operation_id = request.operation_id
        forbidden_roots.extend([Path(request.app_dir), Path(request.program_data_root), Path(request.data_root)])
        command_io.require_safe_result_path(
            result_path,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
        result_path_safe = True
        stores = FilesystemStores.from_request(
            request,
            install_root=expected_app_dir,
            program_data_root=expected_program_data,
        ).as_lifecycle_stores()
        result = restore_action.restore(
            stores,
            request,
            source,
            args.sha256,
            WindowsColdRestore(SubprocessCommandRunner()),
            restore_mode=args.restore_mode,
            source_isolated_confirmed=bool(args.source_isolated),
        )
    except (LifecycleError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        result = CommandResult(schema=RESULT_SCHEMA, ok=False, command="restore", operation_id=operation_id,
            phase="failed_recoverable", code=exc.code if isinstance(exc, LifecycleError) else "restore_input_invalid",
            message="Restore not completed. Keep the source backup and candidate; use a new isolated target after diagnosing the failure.",
            installation_published=False,
            restore_mode="cross_machine" if args.restore_mode == "cross-machine" else "same_environment")
    if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
        command_io.write_result_if_safe(
            result_path,
            result,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
