"""Manifest parsing, filesystem scanning, atomic staging, and ACL helpers for Windows shipments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA

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
_SYNC_TEMP_DIR_NAME = "_sync_tmp"


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
