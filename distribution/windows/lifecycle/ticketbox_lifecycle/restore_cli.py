"""Administrator-only R1 entry, using the existing lifecycle authority and adapters."""

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
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="R1 same-environment recovery into a clean isolated Windows installation")
    parser.add_argument("command", choices=("restore",))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-isolated", action="store_true", required=True)
    args = parser.parse_args(argv)
    operation_id = "unknown"
    try:
        require_windows()
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("restore_admin_required", "R1 requires an administrator")
        source = Path(args.source)
        if not source.is_absolute() or source.drive.startswith("\\\\") or source.suffix.lower() != ".tbxcold":
            raise LifecycleError("restore_source_invalid", "select an absolute local cold-copy file")
        request = command_io.parse_request(json.loads(Path(args.request).read_text(encoding="utf-8")), command="restore")
        operation_id = request.operation_id
        stores = FilesystemStores.from_request(request).as_lifecycle_stores()
        result = restore_action.restore(stores, request, source, args.sha256, WindowsColdRestore(SubprocessCommandRunner()))
    except (LifecycleError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        result = CommandResult(schema=RESULT_SCHEMA, ok=False, command="restore", operation_id=operation_id,
            phase="failed_recoverable", code=exc.code if isinstance(exc, LifecycleError) else "restore_input_invalid",
            message="Restore not completed. Keep the source backup and candidate; use a new isolated target after diagnosing the failure.",
            installation_published=False)
    command_io.write_result(Path(args.result), result)
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
