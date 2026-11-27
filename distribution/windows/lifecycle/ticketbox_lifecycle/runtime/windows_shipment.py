from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_shipment_fs import (
    _STAGED_SHARED_FILES,
    _SYNC_TEMP_DIR_NAME,
    _absolute_path_key,
    _actual_files,
    _atomic_copy_file,
    _cleanup_temp_dir,
    _expected_directories,
    _expected_files,
    _normalize_allowed_siblings,
    _parse_manifest,
    _publish_and_verify_tree_acls,
    _release_dir_matches,
    _resolve_external_staged_files,
    _scan_stage_files,
    _sha256,
    _sync_directory_tree,
    _verify_file_hashes,
)
from ticketbox_lifecycle.schemas import InstallationBinding, InstallRequest

UPGRADE_STAGE_DIR_NAME = "Ticketbox-UpgradeStage"
PG_SERVICE_NAME = "TicketboxPg"
BACKEND_SERVICE_NAME = "TicketboxBackend"
PG_PORT = 5432
BACKEND_PORT = 8000
POSTGRES_MAJOR = 17

__all__ = [
    "BACKEND_PORT",
    "BACKEND_SERVICE_NAME",
    "PG_PORT",
    "PG_SERVICE_NAME",
    "POSTGRES_MAJOR",
    "UPGRADE_STAGE_DIR_NAME",
    "WindowsShipmentVerifier",
    "_absolute_path_key",
    "_expected_files",
    "_parse_manifest",
    "_publish_and_verify_tree_acls",
    "expected_upgrade_stage_root",
]


def expected_upgrade_stage_root(app_dir: Path, release_id: str) -> Path:
    return app_dir.parent / UPGRADE_STAGE_DIR_NAME / release_id


class WindowsShipmentVerifier:
    def __init__(self, expected_app_dir: Path, expected_program_data_root: Path) -> None:
        self._expected_app_dir = expected_app_dir
        self._expected_program_data_root = expected_program_data_root

    def verify_connector_payload(self, binding: InstallationBinding) -> None:
        """Read-only diagnostics qualify the four connector files, not the whole release."""
        app_dir = self._expected_app_dir
        manifest_path = app_dir / "releases" / binding.active_release_id / "release-manifest.json"
        reject_reparse_components(manifest_path)
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding.release_manifest_sha256:
            raise LifecycleViolation("release_hash_mismatch", "installed release manifest changed")
        manifest = _parse_manifest(raw, binding.active_release_id)
        expected = _expected_files(manifest, app_dir, manifest_path)
        root = app_dir / "releases" / binding.active_release_id / "connector"
        for name in ("cloudflared.exe", "config.json", "profile.json", "LICENSE"):
            path = root / name
            reject_reparse_components(path)
            record = expected.get(path.relative_to(app_dir).as_posix().casefold())
            if record is None or path.stat().st_size != record["size"] or _sha256(path) != record["sha256"]:
                raise LifecycleViolation("connector_payload_changed", "connector payload does not match the installed release")
        if manifest_path.read_bytes() != raw:
            raise LifecycleViolation("release_manifest_changed", "installed manifest changed during observation")

    def bind_and_verify(
        self,
        request: InstallRequest,
        *,
        allowed_sibling_releases: frozenset[str] = frozenset(),
    ) -> InstallRequest:
        app_dir = Path(request.app_dir)
        self._require_request_roots(request, app_dir)
        manifest_path = app_dir / "releases" / request.target_release_id / "release-manifest.json"
        manifest, manifest_bytes, actual_manifest_sha = self._read_and_bind_manifest(request, manifest_path)
        expected = _expected_files(manifest, app_dir, manifest_path)
        siblings = _normalize_allowed_siblings(allowed_sibling_releases, request.target_release_id)
        manifest_relative = manifest_path.relative_to(app_dir).as_posix().casefold()
        actual = _actual_files(
            app_dir,
            manifest_path,
            active_release_id=request.target_release_id,
            allowed_siblings=siblings,
            expected_dirs=_expected_directories(expected, manifest_relative),
        )
        if set(expected) != set(actual):
            raise LifecycleViolation(
                "shipment_file_set_mismatch",
                "immutable shipment has missing or unexpected files",
            )
        _verify_file_hashes(expected, actual)
        if manifest_path.read_bytes() != manifest_bytes:
            raise LifecycleViolation(
                "release_manifest_changed",
                "release manifest changed during immutable shipment verification",
            )
        return _bind_manifest_fields(request, manifest, actual_manifest_sha)

    def verify_staged_release(
        self,
        request: InstallRequest,
        *,
        staged_release_root: Path,
        require_target_absent: bool = False,
    ) -> InstallRequest:
        app_dir = Path(request.app_dir)
        self._require_request_roots(request, app_dir)
        if require_target_absent and os.path.lexists(app_dir / "releases" / request.target_release_id):
            raise LifecycleViolation(
                "upgrade_target_release_exists",
                "target release directory already exists before upgrade started; refusing to delete unknown directory",
            )
        _require_trusted_stage_root(self._expected_app_dir, staged_release_root, request.target_release_id)
        manifest_path = staged_release_root / "release-manifest.json"
        manifest, manifest_bytes, actual_manifest_sha = self._read_and_bind_manifest(request, manifest_path)
        virtual_manifest = app_dir / "releases" / request.target_release_id / "release-manifest.json"
        expected = _expected_files(manifest, app_dir, virtual_manifest)
        staged_files = _scan_stage_files(staged_release_root, expected, request.target_release_id)
        resolved = _resolve_external_staged_files(expected, staged_files, app_dir, request.target_release_id)
        _verify_file_hashes(expected, resolved)
        if manifest_path.read_bytes() != manifest_bytes:
            raise LifecycleViolation(
                "release_manifest_changed",
                "staged release manifest changed during verification",
            )
        return _bind_manifest_fields(request, manifest, actual_manifest_sha)

    def materialize_staged_release(
        self,
        request: InstallRequest,
        *,
        staged_release_root: Path,
        publish_acl: Callable[..., None] | None = None,
        verify_acl: Callable[..., None] | None = None,
    ) -> None:
        self.verify_staged_release(request, staged_release_root=staged_release_root)
        app_dir = Path(request.app_dir)
        manifest_path = staged_release_root / "release-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = _parse_manifest(manifest_bytes, request.target_release_id)
        virtual_manifest = app_dir / "releases" / request.target_release_id / "release-manifest.json"
        expected = _expected_files(manifest, app_dir, virtual_manifest)
        release_prefix = f"releases/{request.target_release_id.casefold()}/"
        release_expected = {
            key[len(release_prefix) :]: record
            for key, record in expected.items()
            if key.startswith(release_prefix)
        }
        dest_root = app_dir / "releases" / request.target_release_id
        if _release_dir_matches(dest_root, release_expected, manifest_bytes):
            _publish_and_verify_tree_acls(dest_root, publish_acl=publish_acl, verify_acl=verify_acl)
            return
        if dest_root.exists():
            reject_reparse_components(dest_root)
            shutil.rmtree(dest_root)
        temp_dir = staged_release_root / _SYNC_TEMP_DIR_NAME
        try:
            for rel_key in sorted(release_expected):
                src = staged_release_root / Path(release_expected[rel_key]["path"]).relative_to(
                    Path("releases") / request.target_release_id
                )
                dst = dest_root / Path(release_expected[rel_key]["path"]).relative_to(
                    Path("releases") / request.target_release_id
                )
                _atomic_copy_file(src, dst, temp_dir=temp_dir, publish_acl=publish_acl)
            _atomic_copy_file(
                manifest_path,
                dest_root / "release-manifest.json",
                temp_dir=temp_dir,
                publish_acl=publish_acl,
            )
        finally:
            _cleanup_temp_dir(temp_dir)
        if not _release_dir_matches(dest_root, release_expected, manifest_bytes):
            raise LifecycleViolation(
                "shipment_file_mismatch",
                "materialized target release failed post-copy verification",
            )
        _publish_and_verify_tree_acls(dest_root, publish_acl=publish_acl, verify_acl=verify_acl)

    def cleanup_uncommitted_target_release(self, request: InstallRequest) -> None:
        app_dir = Path(request.app_dir)
        if _absolute_path_key(app_dir) != _absolute_path_key(self._expected_app_dir):
            raise LifecycleViolation(
                "untrusted_install_root",
                "installed application root must be the exact Ticketbox Program Files directory",
            )
        dest_root = app_dir / "releases" / request.target_release_id
        if dest_root.exists():
            reject_reparse_components(dest_root)
            shutil.rmtree(dest_root)

    def sync_staged_shared_payload(
        self,
        request: InstallRequest,
        *,
        staged_release_root: Path,
        allowed_sibling_releases: frozenset[str] = frozenset(),
        publish_acl: Callable[..., None] | None = None,
        verify_acl: Callable[..., None] | None = None,
    ) -> None:
        """Promote staged shared files into active roots using out-of-tree temp files."""
        self.verify_staged_release(request, staged_release_root=staged_release_root)
        app_dir = Path(request.app_dir)
        temp_dir = staged_release_root / _SYNC_TEMP_DIR_NAME
        synced_files: list[Path] = []
        synced_lifecycle_dir: Path | None = None
        try:
            staged_lifecycle = staged_release_root / "lifecycle"
            if staged_lifecycle.is_dir():
                synced_lifecycle_dir = app_dir / "bin" / "lifecycle"
                _sync_directory_tree(
                    staged_lifecycle,
                    synced_lifecycle_dir,
                    temp_dir=temp_dir,
                    publish_acl=publish_acl,
                )
            for dest_rel, staged_rel in _STAGED_SHARED_FILES.items():
                staged_file = staged_release_root / Path(staged_rel)
                if staged_file.is_file():
                    target_file = app_dir / Path(dest_rel)
                    _atomic_copy_file(
                        staged_file,
                        target_file,
                        temp_dir=temp_dir,
                        publish_acl=publish_acl,
                    )
                    synced_files.append(target_file)
        finally:
            _cleanup_temp_dir(temp_dir)
        if synced_lifecycle_dir is not None:
            _publish_and_verify_tree_acls(
                synced_lifecycle_dir,
                publish_acl=publish_acl,
                verify_acl=verify_acl,
            )
        if verify_acl is not None:
            for target_file in synced_files:
                verify_acl(target_file, is_dir=False)
        self.bind_and_verify(
            request,
            allowed_sibling_releases=allowed_sibling_releases,
        )

    def verify_release_manifest(self, binding: InstallationBinding) -> dict[str, object]:
        """Verify and parse the bound release-manifest.json without walking sibling releases."""
        app_dir = self._expected_app_dir
        manifest_path = app_dir / "releases" / binding.active_release_id / "release-manifest.json"
        reject_reparse_components(manifest_path)
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise LifecycleViolation(
                "missing_release_manifest",
                "installed release manifest is absent",
            ) from exc
        if hashlib.sha256(manifest_bytes).hexdigest() != binding.release_manifest_sha256:
            raise LifecycleViolation("release_hash_mismatch", "installed release changed since binding publication")
        return _parse_manifest(manifest_bytes, binding.active_release_id)

    def verify_installed(
        self,
        binding: InstallationBinding,
        *,
        allowed_sibling_releases: frozenset[str] | None = None,
    ) -> dict[str, object]:
        """Read-only payload qualification; does not synthesize Setup authority."""
        app_dir = self._expected_app_dir
        manifest_path = app_dir / "releases" / binding.active_release_id / "release-manifest.json"
        reject_reparse_components(manifest_path)
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != binding.release_manifest_sha256:
            raise LifecycleViolation("release_hash_mismatch", "installed release changed since binding publication")
        manifest = _parse_manifest(manifest_bytes, binding.active_release_id)
        expected = _expected_files(manifest, app_dir, manifest_path)
        if allowed_sibling_releases is None:
            previous = getattr(binding, "previous_release_id", None)
            allowed_sibling_releases = (
                frozenset({previous}) if isinstance(previous, str) and previous else frozenset()
            )
        siblings = _normalize_allowed_siblings(allowed_sibling_releases, binding.active_release_id)
        manifest_relative = manifest_path.relative_to(app_dir).as_posix().casefold()
        actual = _actual_files(
            app_dir,
            manifest_path,
            active_release_id=binding.active_release_id,
            allowed_siblings=siblings,
            expected_dirs=_expected_directories(expected, manifest_relative),
        )
        if set(expected) != set(actual):
            raise LifecycleViolation("shipment_file_set_mismatch", "immutable shipment has missing or unexpected files")
        _verify_file_hashes(expected, actual, mismatch_message="installed immutable payload changed")
        if manifest_path.read_bytes() != manifest_bytes:
            raise LifecycleViolation("release_manifest_changed", "installed manifest changed during verification")
        return manifest

    def _require_request_roots(self, request: InstallRequest, app_dir: Path) -> None:
        if _absolute_path_key(app_dir) != _absolute_path_key(self._expected_app_dir):
            raise LifecycleViolation(
                "untrusted_install_root",
                "installed application root must be the exact Ticketbox Program Files directory",
            )
        _require_trusted_setup_contract(request, self._expected_program_data_root)

    @staticmethod
    def _read_and_bind_manifest(
        request: InstallRequest,
        manifest_path: Path,
    ) -> tuple[dict[str, object], bytes, str]:
        reject_reparse_components(manifest_path)
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise LifecycleViolation(
                "missing_release_manifest",
                "installed release manifest is absent",
            ) from exc
        actual_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        declared_manifest_sha = request.release_manifest_sha256.strip().lower()
        if declared_manifest_sha in {"", "pending"} or declared_manifest_sha != actual_manifest_sha:
            raise LifecycleViolation(
                "release_hash_mismatch",
                "installed release manifest does not match this Setup request",
            )
        prefix = {
            "restore": "restore",
            "upgrade": "upgrade",
            "reinstall": "reinstall",
            "uninstall": "uninstall",
        }.get(request.command, "fresh")
        if request.operation_id != f"{prefix}-{actual_manifest_sha}":
            raise LifecycleViolation(
                "untrusted_setup_request",
                "privileged request does not match the trusted Setup contract",
            )
        manifest = _parse_manifest(manifest_bytes, request.target_release_id)
        return manifest, manifest_bytes, actual_manifest_sha


def _bind_manifest_fields(
    request: InstallRequest,
    manifest: dict[str, object],
    actual_manifest_sha: str,
) -> InstallRequest:
    return replace(
        request,
        release_manifest_sha256=actual_manifest_sha,
        schema_revision=str(manifest["max_schema_revision"]),
        schema_min_compatible=str(manifest["product_version"]),
        semantic_revision=str(manifest["min_semantic_revision"]),
    )


def _require_trusted_stage_root(app_dir: Path, staged_release_root: Path, release_id: str) -> None:
    expected = expected_upgrade_stage_root(app_dir, release_id)
    if _absolute_path_key(staged_release_root) != _absolute_path_key(expected):
        raise LifecycleViolation(
            "untrusted_stage_root",
            "upgrade staged release root must be the protected Program Files stage directory",
        )
    reject_reparse_components(staged_release_root)
    if not staged_release_root.is_dir():
        raise LifecycleViolation("staged_release_missing", "staged upgrade release root is absent")


def _require_trusted_setup_contract(
    request: InstallRequest,
    expected_program_data_root: Path,
) -> None:
    trusted = (
        _absolute_path_key(expected_program_data_root),
        _absolute_path_key(expected_program_data_root / "data"),
        PG_SERVICE_NAME,
        BACKEND_SERVICE_NAME,
        PG_PORT,
        BACKEND_PORT,
        POSTGRES_MAJOR,
    )
    supplied = (
        _absolute_path_key(Path(request.program_data_root)),
        _absolute_path_key(Path(request.data_root)),
        request.pg_service_name,
        request.backend_service_name,
        request.pg_port,
        request.backend_port,
        request.postgres_major,
    )
    if supplied != trusted:
        raise LifecycleViolation(
            "untrusted_setup_request",
            "privileged request does not match the trusted Setup contract",
        )
