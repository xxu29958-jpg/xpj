from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallationBinding, InstallRequest

_MANIFEST_KEYS = {
    "schema",
    "release_id",
    "product_version",
    "lifecycle_compatibility",
    "min_schema_revision",
    "max_schema_revision",
    "min_semantic_revision",
    "signing_state",
    "immutable_payload",
}
_FILE_KEYS = {"path", "size", "sha256"}
_PRODUCT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_RELEASE_ID_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")
_STAGED_SHARED_FILES = {
    "bin/vc_redist.x64.exe": "_staging/vc_redist.x64.exe",
    "ticketbox.ico": "_staging/ticketbox.ico",
}
UPGRADE_STAGE_DIR_NAME = "Ticketbox-UpgradeStage"
_SYNC_TEMP_DIR_NAME = "_sync_tmp"
PG_SERVICE_NAME = "TicketboxPg"
BACKEND_SERVICE_NAME = "TicketboxBackend"
PG_PORT = 5432
BACKEND_PORT = 8000
POSTGRES_MAJOR = 17


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


def _verify_file_hashes(
    expected: dict[str, dict[str, object]],
    resolved: dict[str, Path],
    *,
    mismatch_message: str | None = None,
) -> None:
    for key, record in expected.items():
        path = resolved[key]
        if path.stat().st_size != record["size"] or _sha256(path) != record["sha256"]:
            raise LifecycleViolation(
                "shipment_file_mismatch",
                mismatch_message or f"immutable shipment file does not match: {record['path']}",
            )


def _expected_stage_keys(
    expected: dict[str, dict[str, object]],
    target_release_id: str,
) -> tuple[set[str], set[str]]:
    release_prefix = f"releases/{target_release_id.casefold()}/"
    staged_keys: set[str] = {"release-manifest.json"}
    for key in expected:
        if key.startswith(release_prefix):
            staged_keys.add(key[len(release_prefix) :])
        elif key.startswith("bin/lifecycle/"):
            staged_keys.add("lifecycle/" + key[len("bin/lifecycle/") :])
        elif key in _STAGED_SHARED_FILES:
            staged_keys.add(_STAGED_SHARED_FILES[key].casefold())
    expected_dirs = _directories_for_keys(staged_keys)
    return staged_keys, expected_dirs


def _scan_stage_files(
    staged_root: Path,
    expected: dict[str, dict[str, object]],
    target_release_id: str,
) -> dict[str, Path]:
    expected_stage_keys, expected_dirs = _expected_stage_keys(expected, target_release_id)
    files_map: dict[str, Path] = {}
    for root, directories, files in os.walk(staged_root, topdown=True, followlinks=False):
        root_path = Path(root)
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        kept_dirs: list[str] = []
        for name in directories:
            dir_path = root_path / name
            _require_regular_path(dir_path, directory=True)
            rel_dir = dir_path.relative_to(staged_root).as_posix().casefold()
            if rel_dir == _SYNC_TEMP_DIR_NAME:
                continue
            if rel_dir not in expected_dirs:
                raise LifecycleViolation(
                    "shipment_file_set_mismatch",
                    "staged upgrade release contains an unexpected directory",
                )
            kept_dirs.append(name)
        directories[:] = kept_dirs
        for name in files:
            file_path = root_path / name
            _require_regular_path(file_path, directory=False)
            key = file_path.relative_to(staged_root).as_posix().casefold()
            if key not in expected_stage_keys or key in files_map:
                raise LifecycleViolation(
                    "shipment_file_set_mismatch",
                    "staged upgrade release has unexpected or colliding files",
                )
            files_map[key] = file_path
    if set(files_map) != expected_stage_keys:
        raise LifecycleViolation(
            "shipment_file_set_mismatch",
            "staged upgrade release is incomplete",
        )
    return files_map


def _resolve_external_staged_files(
    expected: dict[str, dict[str, object]],
    staged_files: dict[str, Path],
    app_dir: Path,
    target_release_id: str,
) -> dict[str, Path]:
    release_prefix = f"releases/{target_release_id.casefold()}/"
    resolved: dict[str, Path] = {}
    for key, record in expected.items():
        if key.startswith(release_prefix):
            path = staged_files.get(key[len(release_prefix) :])
        elif key.startswith("bin/lifecycle/"):
            path = staged_files.get("lifecycle/" + key[len("bin/lifecycle/") :])
        elif key in _STAGED_SHARED_FILES:
            path = staged_files.get(_STAGED_SHARED_FILES[key].casefold())
        else:
            candidate = app_dir / Path(str(record["path"]))
            _require_regular_path(candidate, directory=False)
            path = candidate
        if path is None:
            raise LifecycleViolation(
                "shipment_file_set_mismatch",
                "staged upgrade release is missing a required file",
            )
        resolved[key] = path
    return resolved


def _release_dir_matches(
    dest_root: Path,
    release_expected: dict[str, dict[str, object]],
    manifest_bytes: bytes,
) -> bool:
    if not dest_root.is_dir():
        return False
    try:
        reject_reparse_components(dest_root)
        manifest_path = dest_root / "release-manifest.json"
        if not manifest_path.is_file() or manifest_path.read_bytes() != manifest_bytes:
            return False
        expected_keys = set(release_expected) | {"release-manifest.json"}
        expected_dirs = _directories_for_keys(expected_keys)
        observed: dict[str, Path] = {}
        for root, directories, files in os.walk(dest_root, topdown=True, followlinks=False):
            root_path = Path(root)
            for name in directories:
                dir_path = root_path / name
                _require_regular_path(dir_path, directory=True)
                if dir_path.relative_to(dest_root).as_posix().casefold() not in expected_dirs:
                    return False
            for name in files:
                file_path = root_path / name
                _require_regular_path(file_path, directory=False)
                key = file_path.relative_to(dest_root).as_posix().casefold()
                if key in observed:
                    return False
                observed[key] = file_path
        if set(observed) != expected_keys:
            return False
        for key, record in release_expected.items():
            path = observed[key]
            if path.stat().st_size != record["size"] or _sha256(path) != record["sha256"]:
                return False
        return True
    except (OSError, LifecycleViolation):
        return False


def _directories_for_keys(keys: set[str]) -> set[str]:
    dirs: set[str] = set()
    for key in keys:
        parts = PurePosixPath(key).parts[:-1]
        for idx in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:idx]).casefold())
    return dirs


def _expected_directories(
    expected: dict[str, dict[str, object]],
    manifest_relative: str,
) -> set[str]:
    return _directories_for_keys(set(expected) | {manifest_relative})


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


def _absolute_path_key(path: Path) -> str:
    value = os.fspath(path)
    if not os.path.isabs(value):
        raise LifecycleViolation("untrusted_install_root", "installed application root must be absolute")
    return os.path.normcase(os.path.normpath(value))


def _parse_manifest(payload: bytes, release_id: str) -> dict[str, object]:
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleViolation("release_manifest_invalid", "release manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise LifecycleViolation("release_manifest_invalid", "release manifest shape is not closed")
    if (
        manifest["schema"] != "ticketbox-release-manifest-v1"
        or manifest["release_id"] != release_id
        or not isinstance(manifest["product_version"], str)
        or _PRODUCT_VERSION.fullmatch(manifest["product_version"]) is None
        or manifest["product_version"] != release_id
        or manifest["lifecycle_compatibility"] != [REQUEST_SCHEMA]
        or manifest["signing_state"] != "release-bound"
        or not all(
            isinstance(manifest[name], str) and manifest[name]
            for name in (
                "min_schema_revision",
                "max_schema_revision",
                "min_semantic_revision",
            )
        )
    ):
        raise LifecycleViolation("release_manifest_invalid", "release manifest identity is invalid")
    return manifest


def _expected_files(
    manifest: dict[str, object],
    app_dir: Path,
    manifest_path: Path,
) -> dict[str, dict[str, object]]:
    payload = manifest["immutable_payload"]
    if not isinstance(payload, dict) or set(payload) != {"algorithm", "files"}:
        raise LifecycleViolation("release_manifest_invalid", "immutable payload shape is not closed")
    files = payload["files"]
    if payload["algorithm"] != "SHA-256" or not isinstance(files, list) or not files:
        raise LifecycleViolation("release_manifest_invalid", "immutable payload inventory is invalid")
    manifest_relative = manifest_path.relative_to(app_dir).as_posix().casefold()
    records: dict[str, dict[str, object]] = {}
    for item in files:
        if not isinstance(item, dict) or set(item) != _FILE_KEYS:
            raise LifecycleViolation("release_manifest_invalid", "immutable file record is invalid")
        relative = item["path"]
        size = item["size"]
        digest = item["sha256"]
        if not _canonical_relative(relative):
            raise LifecycleViolation("release_manifest_invalid", "immutable file path is not canonical")
        key = str(relative).casefold()
        if (
            key == manifest_relative
            or key in records
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise LifecycleViolation("release_manifest_invalid", "immutable file evidence is invalid")
        records[key] = item
    return records


def _atomic_copy_file(
    source: Path,
    destination: Path,
    *,
    temp_dir: Path,
    publish_acl: Callable[..., None] | None = None,
) -> None:
    reject_reparse_components(source)
    reject_reparse_components(destination)
    reject_reparse_components(temp_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=destination.name, suffix=".tmp", dir=str(temp_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out, length=1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if publish_acl is not None:
            publish_acl(tmp_path, is_dir=False)
        os.replace(tmp_path, destination)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _sync_directory_tree(
    source_root: Path,
    dest_root: Path,
    *,
    temp_dir: Path,
    publish_acl: Callable[..., None] | None = None,
) -> None:
    reject_reparse_components(source_root)
    reject_reparse_components(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    expected_rel: set[str] = set()
    for root, _dirs, files in os.walk(source_root, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in sorted(files, key=str.casefold):
            src = root_path / name
            rel = src.relative_to(source_root).as_posix()
            expected_rel.add(rel.casefold())
            _atomic_copy_file(
                src,
                dest_root / Path(rel),
                temp_dir=temp_dir,
                publish_acl=publish_acl,
            )
    for root, dirs, files in os.walk(dest_root, topdown=False, followlinks=False):
        root_path = Path(root)
        for name in files:
            path = root_path / name
            if path.relative_to(dest_root).as_posix().casefold() not in expected_rel:
                reject_reparse_components(path)
                path.unlink()
        for name in dirs:
            path = root_path / name
            reject_reparse_components(path)
            if not any(path.iterdir()):
                path.rmdir()


def _publish_and_verify_tree_acls(
    root: Path,
    *,
    publish_acl: Callable[..., None] | None,
    verify_acl: Callable[..., None] | None,
) -> None:
    if publish_acl is None and verify_acl is None:
        return
    reject_reparse_components(root)
    directories: list[Path] = [root]
    files: list[Path] = []
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        dirs.sort(key=str.casefold)
        names.sort(key=str.casefold)
        current_path = Path(current)
        for name in dirs:
            directories.append(current_path / name)
        for name in names:
            files.append(current_path / name)
    if publish_acl is not None:
        for directory in directories:
            publish_acl(directory, is_dir=True)
        for file_path in files:
            publish_acl(file_path, is_dir=False)
    if verify_acl is not None:
        for directory in directories:
            verify_acl(directory, is_dir=True)
        for file_path in files:
            verify_acl(file_path, is_dir=False)


def _cleanup_temp_dir(temp_dir: Path) -> None:
    if temp_dir.exists():
        reject_reparse_components(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)


def _normalize_allowed_siblings(
    allowed_sibling_releases: frozenset[str],
    active_release_id: str,
) -> frozenset[str]:
    normalized: set[str] = set()
    active_folded = active_release_id.casefold()
    for sibling in allowed_sibling_releases:
        if not isinstance(sibling, str) or _RELEASE_ID_PATTERN.fullmatch(sibling) is None:
            raise LifecycleViolation("invalid_release_transition", "allowed sibling release id is invalid")
        folded = sibling.casefold()
        if folded != active_folded:
            normalized.add(folded)
    return frozenset(normalized)


def _is_allowed_sibling_release_path(relative: str, allowed_siblings: frozenset[str]) -> bool:
    if not allowed_siblings:
        return False
    parts = PurePosixPath(relative).parts
    return (
        len(parts) >= 2
        and parts[0].casefold() == "releases"
        and parts[1].casefold() in allowed_siblings
    )


def _actual_files(
    app_dir: Path,
    manifest_path: Path,
    *,
    active_release_id: str,
    allowed_siblings: frozenset[str] = frozenset(),
    expected_dirs: set[str] | None = None,
) -> dict[str, Path]:
    reject_reparse_components(app_dir)
    if not app_dir.is_dir():
        raise LifecycleViolation("shipment_missing", "immutable shipment root is absent")
    manifest_relative = manifest_path.relative_to(app_dir).as_posix().casefold()
    allowed_releases = allowed_siblings | {active_release_id.casefold()}
    records: dict[str, Path] = {}
    for root, directories, files in os.walk(app_dir, topdown=True, followlinks=False):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        root_path = Path(root)
        is_releases_root = root_path == app_dir / "releases"
        for name in directories:
            dir_path = root_path / name
            _require_regular_path(dir_path, directory=True)
            rel_dir = dir_path.relative_to(app_dir).as_posix()
            if is_releases_root and name.casefold() not in allowed_releases:
                raise LifecycleViolation(
                    "shipment_file_set_mismatch",
                    "immutable shipment contains an unexpected release directory",
                )
            if _is_allowed_sibling_release_path(rel_dir, allowed_siblings):
                continue
            if expected_dirs is not None and rel_dir.casefold() not in expected_dirs:
                raise LifecycleViolation(
                    "shipment_file_set_mismatch",
                    "immutable shipment contains an unexpected directory",
                )
        for name in files:
            path = root_path / name
            _require_regular_path(path, directory=False)
            relative = path.relative_to(app_dir).as_posix()
            if _is_allowed_sibling_release_path(relative, allowed_siblings):
                continue
            key = relative.casefold()
            if key == manifest_relative:
                continue
            if key in records:
                raise LifecycleViolation("shipment_file_set_mismatch", "immutable shipment paths collide")
            records[key] = path
    return records


def _require_regular_path(path: Path, *, directory: bool) -> None:
    reject_reparse_components(path)
    try:
        observed = path.lstat()
    except OSError as exc:
        raise LifecycleViolation("shipment_unreadable", "immutable shipment path is unreadable") from exc
    valid = stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode)
    if not valid:
        raise LifecycleViolation("shipment_path_invalid", "immutable shipment contains a non-regular path")


def _canonical_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    if any(ord(char) < 0x20 or ord(char) > 0x7E for char in value):
        return False
    parsed = PurePosixPath(value)
    return (
        not parsed.is_absolute()
        and str(parsed) == value
        and all(part not in {".", ".."} for part in parsed.parts)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
