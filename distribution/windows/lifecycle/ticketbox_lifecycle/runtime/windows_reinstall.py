"""Windows runtime mechanics for narrow reinstall preserving verified data."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_shipment import _publish_and_verify_tree_acls
from ticketbox_lifecycle.runtime.windows_shortcut import update_manager_start_menu_shortcut
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest


class WindowsReinstallPlatform:
    def __init__(
        self,
        runner: CommandRunner,
        security: WindowsSecurityAdapter,
        dataset: WindowsDatasetAdapter | None = None,
        *,
        shortcut_updater: Callable[[InstallRequest], None] | None = None,
    ) -> None:
        self._runner = runner
        self._security = security
        self._dataset = dataset if dataset is not None else WindowsDatasetAdapter(runner, security)
        self._shortcut_updater = shortcut_updater

    def publish_and_verify_program_acls(self, request: InstallRequest) -> None:
        publish_acl = getattr(self._security, "publish_installed_program_acl", None)
        verify_acl = getattr(self._security, "verify_installed_program_acl", None)
        if not callable(publish_acl) and not callable(verify_acl):
            return
        app_dir = Path(request.app_dir)
        for tree in (app_dir / "releases" / request.target_release_id, app_dir / "bin" / "lifecycle"):
            if tree.is_dir():
                _publish_and_verify_tree_acls(
                    tree,
                    publish_acl=publish_acl if callable(publish_acl) else None,
                    verify_acl=verify_acl if callable(verify_acl) else None,
                )

    def verify_preserved_dataset(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> dict[str, object]:
        return self._dataset.verify_preserved_dataset(request, binding)

    def verify_candidate_health(self, request: InstallRequest) -> None:
        self._dataset.wait_for_runtime_mode(request, expected_mode="upgrade_verify_only")
        self._dataset.verify_runtime_mode(request, expected_mode="upgrade_verify_only")

    def verify_normal_health(self, request: InstallRequest) -> None:
        self._dataset.wait_for_runtime_mode(request, expected_mode="normal")
        self._dataset.verify_runtime_mode(request, expected_mode="normal")

    def update_start_menu_shortcut(self, request: InstallRequest) -> None:
        if self._shortcut_updater is not None:
            self._shortcut_updater(request)
            return
        update_manager_start_menu_shortcut(request)
