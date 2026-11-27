"""Administrator-only narrow reinstall entry preserving verified existing data."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
from typing import cast

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain import reinstall as reinstall_action
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_reinstall import WindowsReinstallPlatform
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.runtime.windows_shipment import _absolute_path_key
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        description="Reinstall Ticketbox program and services over verified preserved data without initdb",
    )
    parser.add_argument("command", choices=("reinstall",))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    operation_id = "unknown"
    forbidden_roots: list[Path] = []
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
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("reinstall_admin_required", "preserved-data reinstall requires an administrator")
        payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
        operation_id = str(payload.get("operation_id") or "unknown")
        request = command_io.parse_request(payload, command="reinstall")
        operation_id = request.operation_id
        forbidden_roots.extend([
            Path(request.app_dir),
            Path(request.program_data_root),
            Path(request.data_root),
        ])
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        result_path_safe = True
        if _absolute_path_key(Path(request.app_dir)) != _absolute_path_key(expected_app_dir):
            raise LifecycleViolation(
                "untrusted_install_root",
                "installed application root must be the exact Ticketbox Program Files directory",
            )
        if _absolute_path_key(Path(request.program_data_root)) != _absolute_path_key(expected_program_data):
            raise LifecycleViolation(
                "untrusted_setup_request",
                "privileged request does not match the trusted ProgramData root",
            )
        command_io.write_result(
            result_path,
            CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command="reinstall",
                operation_id=operation_id,
                phase="prepared",
                code="running",
                message="preserved-data reinstall started",
                installation_published=None,
            ),
        )
        fs_stores = FilesystemStores.from_request(
            request,
            install_root=expected_app_dir,
            program_data_root=expected_program_data,
        )
        platform = WindowsReinstallPlatform(
            SubprocessCommandRunner(),
            cast(WindowsSecurityAdapter, fs_stores._adapters.security),
            cast(WindowsDatasetAdapter, fs_stores._adapters.dataset),
        )
        result = reinstall_action.reinstall(fs_stores.as_lifecycle_stores(), request, platform)
    except LifecycleError as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="reinstall",
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
            command="reinstall",
            operation_id=operation_id,
            phase="failed_recoverable",
            code="unhandled",
            message="unexpected preserved-data reinstall failure",
            installation_published=None,
        )
    if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
        command_io.write_result_if_safe(result_path, result, forbidden_roots=forbidden_roots)
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
