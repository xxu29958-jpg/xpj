"""Explicit administrator cold retention; the installed sources are read only."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import zipfile
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.cold_archive import verify_archive, write_archive
from ticketbox_lifecycle.runtime.cold_installation import ColdInstallation
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import os_mutex
from ticketbox_lifecycle.runtime.windows_adapters import WindowsAdapterBundle
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_control_root,
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components, require_windows
from ticketbox_lifecycle.runtime.windows_shipment import BACKEND_SERVICE_NAME


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Internal Beta cold retention and verification; no installation restore.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cold-copy", help="Create a new copy after the administrator stops both services").add_argument("--output", required=True)
    commands.add_parser("verify-cold-copy", help="Read all archived bytes without extraction or restore").add_argument("--source", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "cold-copy":
            result = create_cold_copy(Path(args.output))
        else:
            reject_reparse_components(Path(args.source))
            with Path(args.source).open("rb") as source:
                result = verify_archive(source)
        print(json.dumps({"ok": True, "command": args.command, **result}))
        return 0
    except LifecycleError as exc:
        code = exc.code
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        code = "cold_io_or_corrupt"
    print(json.dumps({"ok": False, "code": code, "message": "Cold copy or verification incomplete. Keep original data; check stopped services and the output file. Failed files are not complete copies."}), file=sys.stderr)
    return 2


def create_cold_copy(output: Path) -> dict[str, object]:
    require_windows()
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise LifecycleError("cold_admin_required", "run the cold copy command as administrator")
    _check_output(output)
    app_dir = ticketbox_install_root()
    program_data = ticketbox_program_data_root()
    for source_root in (app_dir, program_data, ticketbox_control_root()):
        if output.is_relative_to(source_root):
            raise LifecycleError("cold_output_inside_source", "cold copy destination must be outside the installation")
    mutex = os_mutex(ticketbox_control_root() / "lifecycle.lock")
    stores = FilesystemStores(
        program_data / "machine", BACKEND_SERVICE_NAME,
        WindowsAdapterBundle(SubprocessCommandRunner(), WindowsFileSecurity(), NativeWindowsScmObserver()), mutex,
    )
    mutex.acquire()
    try:
        source = ColdInstallation.read(stores, app_dir, program_data)
        with create_private_archive(output) as target:
            result = write_archive(target, source.roots(), source.identity(), source.require_stopped)
            target.seek(0)
            if verify_archive(target) != result:
                raise LifecycleError("cold_corrupt", "completed copy could not be read back")
        return result
    finally:
        mutex.release()


def _check_output(path: Path) -> None:
    if (
        not path.is_absolute() or path.drive.startswith("\\\\")
        or ":" in str(path)[2:] or ".." in path.parts or path.suffix.lower() != ".tbxcold"
    ):
        raise LifecycleError("cold_output_invalid", "use a new absolute local .tbxcold file")
    reject_reparse_components(path)
    if path.exists():
        raise LifecycleError("cold_output_exists", "cold copy never overwrites an existing file")
