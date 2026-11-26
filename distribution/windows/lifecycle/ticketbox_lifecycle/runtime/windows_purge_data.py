"""Windows runtime mechanics for standalone permanent host-data deletion."""

from __future__ import annotations

import os
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import scm_query_state, service_exists
from ticketbox_lifecycle.schemas import InstallationBinding


def _validate_delete_tree(root: Path, *, allowed_parent: Path) -> bool:
    reject_reparse_components(allowed_parent)
    reject_reparse_components(root)
    if not os.path.lexists(root):
        return False
    resolved_parent = Path(os.path.abspath(allowed_parent))
    resolved_root = Path(os.path.abspath(root))
    try:
        resolved_root.relative_to(resolved_parent)
    except ValueError as exc:
        raise LifecycleViolation("purge_path_escaped", f"refusing to delete path outside {allowed_parent}") from exc

    if root.is_file():
        return True
    if not root.is_dir():
        raise LifecycleViolation("purge_path_untrusted", f"unexpected filesystem object: {root}")

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        reject_reparse_components(current_path)
        for name in dirs:
            reject_reparse_components(current_path / name)
        for name in files:
            reject_reparse_components(current_path / name)
    return True


def _delete_validated_tree(root: Path) -> bool:
    reject_reparse_components(root)
    if not os.path.lexists(root):
        return False
    if root.is_file():
        root.unlink()
        return True
    for current, dirs, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            reject_reparse_components(path)
            path.unlink()
        for name in dirs:
            path = current_path / name
            reject_reparse_components(path)
            path.rmdir()
    root.rmdir()
    return True


class WindowsPurgeDataPlatform:
    def __init__(
        self,
        runner: CommandRunner,
        *,
        dataset: WindowsDatasetAdapter | None = None,
        app_dir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._dataset = dataset
        self._app_dir = app_dir

    def require_services_stopped(self, binding: InstallationBinding) -> None:
        for name in (binding.backend_service_name, binding.pg_service_name, CONNECTOR_SERVICE_NAME):
            if not service_exists(self._runner, name):
                continue
            state = scm_query_state(self._runner, name)
            if state != "STOPPED":
                raise LifecycleViolation(
                    "purge_services_running",
                    f"service {name} is in state {state}; stop and uninstall services before purging data",
                )

    def verify_local_dataset_identity(
        self,
        binding: InstallationBinding,
        *,
        program_data_root: str,
    ) -> dict[str, object]:
        resolved_app_dir = self._app_dir if self._app_dir is not None else ticketbox_install_root()
        dataset = (
            self._dataset
            if self._dataset is not None
            else WindowsDatasetAdapter(self._runner, WindowsSecurityAdapter(self._runner))
        )
        return dataset.verify_stopped_pgdata_dataset_id(
            binding,
            app_dir=resolved_app_dir,
            program_data_root=Path(program_data_root),
        )

    def purge_authorized_local_data(
        self,
        binding: InstallationBinding,
        *,
        program_data_root: str,
    ) -> list[str]:
        root = Path(program_data_root)
        reject_reparse_components(root)
        data_root = Path(binding.data_root)
        machine_root = root / "machine"
        reject_reparse_components(data_root)
        reject_reparse_components(machine_root)

        declared_targets = (
            data_root / "pgdata",
            data_root / "attachments",
            data_root / "app",
            machine_root / "installation.json",
            machine_root / "operations",
            machine_root / "secrets",
            machine_root / "connectors",
            machine_root / "runtime",
            machine_root / "diagnostics",
        )
        present_targets = [
            candidate
            for candidate in declared_targets
            if _validate_delete_tree(candidate, allowed_parent=root)
        ]

        purged: list[str] = []
        for candidate in present_targets:
            if _delete_validated_tree(candidate):
                purged.append(str(candidate))

        for container in (data_root, machine_root):
            if os.path.lexists(container):
                reject_reparse_components(container)
                if container.is_dir() and not any(container.iterdir()):
                    container.rmdir()
                    purged.append(str(container))
        return purged
