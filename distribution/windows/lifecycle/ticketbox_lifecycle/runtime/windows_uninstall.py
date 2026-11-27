"""Windows runtime mechanics for controlled default uninstall preserving data."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from ticketbox_lifecycle.adapters.scm import ScmObserver
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
from ticketbox_lifecycle.runtime import layout, windows_uninstall_verify
from ticketbox_lifecycle.runtime.cold_installation import read_stopped_cluster
from ticketbox_lifecycle.runtime.command import CommandRunner
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import (
    delete_service,
    service_exists,
    stop_service_and_wait,
)
from ticketbox_lifecycle.runtime.windows_shortcut import remove_manager_start_menu_shortcut
from ticketbox_lifecycle.runtime.windows_uninstall_verify import _norm_path, _raise_walk_error
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest

__all__ = ["WindowsUninstallPlatform"]


class WindowsUninstallPlatform:
    def __init__(
        self,
        runner: CommandRunner,
        observer: ScmObserver,
        *,
        shortcut_remover: Callable[[], bool] | None = None,
    ) -> None:
        self._runner = runner
        self._observer = observer
        self._shortcut_remover = shortcut_remover

    def verify_owned_services(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> None:
        windows_uninstall_verify.verify_owned_services(
            self._runner,
            self._observer,
            request,
            binding,
        )

    def stop_and_unregister_services(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
    ) -> list[str]:
        removed: list[str] = []
        if service_exists(self._runner, CONNECTOR_SERVICE_NAME):
            delete_service(self._runner, CONNECTOR_SERVICE_NAME, code="uninstall_connector_delete_failed")
            removed.append(CONNECTOR_SERVICE_NAME)
        if service_exists(self._runner, binding.backend_service_name):
            delete_service(self._runner, binding.backend_service_name, code="uninstall_backend_delete_failed")
            removed.append(binding.backend_service_name)
        if service_exists(self._runner, binding.pg_service_name):
            stop_service_and_wait(self._runner, binding.pg_service_name, code="uninstall_pg_stop_failed")
            pgdata = layout.pgdata(request)
            if (pgdata / "PG_VERSION").is_file() and (layout.pg_bin(request) / "pg_controldata.exe").is_file():
                read_stopped_cluster(self._runner, layout.pg_bin(request), pgdata)
            delete_service(self._runner, binding.pg_service_name, code="uninstall_pg_delete_failed")
            removed.append(binding.pg_service_name)
        return removed

    def remove_start_menu_shortcut(self, request: InstallRequest) -> bool:
        del request
        if self._shortcut_remover is not None:
            return self._shortcut_remover()
        return remove_manager_start_menu_shortcut()

    def verify_registered_release_manifests(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        release_ids: tuple[str, ...],
        expected_manifests: Mapping[str, str],
        resuming_cleanup: bool = False,
    ) -> None:
        windows_uninstall_verify.plan_registered_release_cleanup(
            request,
            binding,
            release_ids=release_ids,
            expected_manifests=expected_manifests,
            resuming_cleanup=resuming_cleanup,
        )

    @staticmethod
    def _remove_planned_release(
        rid: str,
        release_dir: Path,
        manifest_path: Path | None,
        payload_files: list[Path],
    ) -> None:
        if manifest_path is None:
            if release_dir.is_dir() and not any(release_dir.iterdir()):
                release_dir.rmdir()
        else:
            for file_path in payload_files:
                if os.path.lexists(file_path):
                    reject_reparse_components(file_path)
                    if file_path.is_file():
                        file_path.unlink()
            for root_dir, dirs, _files in os.walk(
                release_dir,
                topdown=False,
                followlinks=False,
                onerror=_raise_walk_error,
            ):
                root_path = Path(root_dir)
                for dirname in dirs:
                    candidate = root_path / dirname
                    reject_reparse_components(candidate)
                    if candidate.is_dir() and not any(candidate.iterdir()):
                        candidate.rmdir()
            remaining = list(release_dir.iterdir())
            if (
                len(remaining) == 1
                and _norm_path(remaining[0]) == _norm_path(manifest_path)
                and manifest_path.is_file()
            ):
                reject_reparse_components(manifest_path)
                manifest_path.unlink()
                release_dir.rmdir()
        if os.path.lexists(release_dir):
            raise LifecycleError(
                "uninstall_release_cleanup_incomplete",
                f"release directory {rid} could not be completely removed after verified cleanup",
            )

    def cleanup_registered_release_payloads(
        self,
        request: InstallRequest,
        binding: InstallationBinding,
        *,
        release_ids: tuple[str, ...],
        expected_manifests: Mapping[str, str] | None = None,
        resuming_cleanup: bool = False,
    ) -> list[str]:
        releases_root = Path(request.app_dir) / "releases"
        planned = windows_uninstall_verify.plan_registered_release_cleanup(
            request,
            binding,
            release_ids=release_ids,
            expected_manifests=expected_manifests,
            resuming_cleanup=resuming_cleanup,
        )
        active_key = binding.active_release_id.casefold()
        ordered_planned = [item for item in planned if item[0].casefold() != active_key] + [
            item for item in planned if item[0].casefold() == active_key
        ]
        removed_releases: list[str] = []
        for rid, release_dir, manifest_path, payload_files in ordered_planned:
            self._remove_planned_release(rid, release_dir, manifest_path, payload_files)
            removed_releases.append(rid)
        if releases_root.is_dir() and not any(releases_root.iterdir()):
            releases_root.rmdir()
        return removed_releases
