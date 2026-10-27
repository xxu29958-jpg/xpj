"""Windows authorization, private destination and archive mechanisms for cold retention."""

from __future__ import annotations

import ctypes
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.adapters.cold_copy import ColdCopySource
from ticketbox_lifecycle.adapters.ports import Mutex
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


@dataclass(frozen=True)
class WindowsColdCopy:
    stores: FilesystemStores
    app_dir: Path
    program_data: Path
    mutex: Mutex

    @classmethod
    def for_output(cls, output: Path) -> WindowsColdCopy:
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
        return cls(stores, app_dir, program_data, mutex)

    def read_source(self) -> ColdCopySource:
        return ColdInstallation.read(self.stores, self.app_dir, self.program_data)

    def create_archive(self, output: Path) -> AbstractContextManager[BinaryIO]:
        return create_private_archive(output)

    def write_archive(self, target: BinaryIO, source: ColdCopySource) -> dict[str, object]:
        return write_archive(target, source.roots(), source.identity(), source.require_stopped)

    def verify_archive(self, target: BinaryIO) -> dict[str, object]:
        return verify_archive(target)


def verify_cold_copy(path: Path) -> dict[str, object]:
    reject_reparse_components(path)
    with path.open("rb") as source:
        return verify_archive(source)


def _check_output(path: Path) -> None:
    if (
        not path.is_absolute() or path.drive.startswith("\\\\")
        or ":" in str(path)[2:] or ".." in path.parts or path.suffix.lower() != ".tbxcold"
    ):
        raise LifecycleError("cold_output_invalid", "use a new absolute local .tbxcold file")
    reject_reparse_components(path)
    if path.exists():
        raise LifecycleError("cold_output_exists", "cold copy never overwrites an existing file")
