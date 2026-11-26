"""A sealed, read-verifiable retention copy; it has no installation/restore writer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components

LEGACY_SCHEMA = "ticketbox-beta-cold-copy-v1"
SCHEMA = "ticketbox-beta-cold-copy-v2"
CONNECTOR_SECRET_ROOT = "machine/connectors/cloudflare/secrets"
CONNECTOR_POLICY = {
    "excluded_directory": CONNECTOR_SECRET_ROOT,
    "credentials": "not_backed_up",
    "after_restore": "configure_again",
}
SECRET_DISPOSITION = {
    "db_bootstrap_material": "included_in_private_copy_for_rebind",
    "service_db_credentials": "rotated_on_restore",
    "connector_secrets": "excluded_reconfigure_on_target",
    "user_wincred_dpapi": "not_included_non_portable",
}
_RECOVERY_POINT_KEYS = frozenset({
    "cutoff_utc",
    "api_version",
    "semantic_revision",
    "schema_revision",
    "secret_disposition",
    "matching_installer_requirement",
})
_MATCHING_INSTALLER_KEYS = frozenset({
    "release_id",
    "release_manifest_sha256",
    "postgres_major",
    "verify_command",
})
MANIFEST = "COLD_COPY.json"
COMPONENTS = frozenset({"program", "machine", "data/pgdata", "data/attachments", "data/app"})
_REQUIRED_FILES = frozenset({
    "data/pgdata/PG_VERSION", "data/pgdata/global/pg_control", "data/app/.env", "machine/installation.json",
    "machine/secrets/postgres.password", "machine/secrets/ticketbox_migrator.password",
    "machine/secrets/ticketbox_runtime.password", "machine/secrets/pgpass",
})
_CHUNK = 1024 * 1024


def build_recovery_point(
    identity: Mapping[str, object],
    *,
    api_version: str = "2026-10-11",
    semantic_revision: str = "ticketbox-dataset-semantics-v1",
    cutoff_utc: str | None = None,
) -> dict[str, object]:
    return {
        "cutoff_utc": cutoff_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_version": api_version,
        "semantic_revision": semantic_revision,
        "schema_revision": str(identity.get("schema_revision") or ""),
        "secret_disposition": dict(SECRET_DISPOSITION),
        "matching_installer_requirement": {
            "release_id": str(identity.get("release_id") or ""),
            "release_manifest_sha256": str(identity.get("release_manifest_sha256") or ""),
            "postgres_major": identity.get("postgres_major"),
            "verify_command": 'TicketboxLifecycle.exe verify-cold-copy --source "<backup.tbxcold>"',
        },
    }


def estimate_source_bytes(
    roots: Mapping[str, Path],
    *,
    exclude_entry: Callable[[str], bool] | None = None,
) -> int:
    if set(roots) != COMPONENTS:
        raise LifecycleError("cold_sources_invalid", "cold copy source set is incomplete")
    sources = _scan(roots, exclude_entry=exclude_entry)
    return sum(path.stat().st_size for path in sources.values() if path is not None)


def write_archive(
    output: BinaryIO,
    roots: Mapping[str, Path],
    identity: dict[str, object],
    require_stopped: Callable[[], None],
    *,
    exclude_entry: Callable[[str], bool] | None = None,
    recovery_point: dict[str, object] | None = None,
) -> dict[str, object]:
    """Keep the output incomplete until the original tree and stop state agree."""
    if set(roots) != COMPONENTS:
        raise LifecycleError("cold_sources_invalid", "cold copy source set is incomplete")
    require_stopped()
    sources = _scan(roots, exclude_entry=exclude_entry)
    if not {name for name, path in sources.items() if path is not None} >= _REQUIRED_FILES:
        raise LifecycleError("cold_source_missing", "required database, identity or credential material is missing")
    records: dict[str, dict[str, object] | None] = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, path in sources.items():
            if path is None:
                archive.writestr(name, b"")
                records[name] = None
            else:
                records[name] = _copy_file(archive, name, path)
        for name, path in sources.items():
            if path is not None and _digest_file(path) != records[name]:
                raise LifecycleError("cold_source_changed", "source bytes changed during cold copy")
        if sources != _scan(roots, exclude_entry=exclude_entry):
            raise LifecycleError("cold_source_changed", "source file set changed during cold copy")
        require_stopped()
        resolved_rp = (
            recovery_point
            if recovery_point is not None
            else build_recovery_point(identity)
        )
        _require_valid_recovery_point(resolved_rp)
        manifest: dict[str, object] = {
            "schema": SCHEMA,
            "complete": True,
            "identity": identity,
            "entries": records,
            "public_connectivity": CONNECTOR_POLICY,
            "recovery_point": resolved_rp,
        }
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    output.flush()
    os.fsync(output.fileno())
    return _summary(manifest)


def verify_archive(source: BinaryIO) -> dict[str, object]:
    """Read every byte without extracting files or running archived programs."""
    with zipfile.ZipFile(source) as archive:
        manifest = _read_manifest(archive)
        for name, expected in manifest["entries"].items():
            if expected is None:
                if not name.endswith("/") or archive.getinfo(name).file_size != 0:
                    raise LifecycleError("cold_corrupt", "cold copy directory entry is invalid")
            else:
                with archive.open(name) as stream:
                    observed = _digest(stream)
                if observed != expected:
                    raise LifecycleError("cold_corrupt", "cold copy file checksum does not match")
    return _summary(manifest)


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    names = archive.namelist()
    if len(names) != len(set(names)) or MANIFEST not in names:
        raise LifecycleError("cold_incomplete", "cold copy has no unique completion manifest")
    manifest = json.loads(archive.read(MANIFEST))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") not in {LEGACY_SCHEMA, SCHEMA}
        or manifest.get("complete") is not True
        or not isinstance(manifest.get("identity"), dict)
        or not isinstance(manifest.get("entries"), dict)
    ):
        raise LifecycleError("cold_incomplete", "cold copy completion manifest is invalid")
    _require_archive_components(manifest, names)
    return manifest


def _require_valid_matching_installer(installer: object) -> None:
    if not isinstance(installer, dict) or set(installer) != _MATCHING_INSTALLER_KEYS:
        raise LifecycleError("cold_recovery_point_invalid", "cold copy matching_installer_requirement is invalid")
    installer_pg = installer.get("postgres_major")
    if (
        not isinstance(installer["release_id"], str)
        or not isinstance(installer["release_manifest_sha256"], str)
        or (installer_pg is not None and (type(installer_pg) is not int or installer_pg <= 0))
        or not isinstance(installer["verify_command"], str)
        or not installer["verify_command"]
    ):
        raise LifecycleError("cold_recovery_point_invalid", "cold copy matching_installer_requirement is invalid")


def _require_valid_recovery_point(recovery_point: object) -> None:
    if not isinstance(recovery_point, dict) or set(recovery_point) != _RECOVERY_POINT_KEYS:
        raise LifecycleError("cold_recovery_point_invalid", "cold copy recovery_point metadata is invalid")
    if (
        not isinstance(recovery_point["cutoff_utc"], str)
        or not recovery_point["cutoff_utc"]
        or not isinstance(recovery_point["api_version"], str)
        or not recovery_point["api_version"]
        or not isinstance(recovery_point["semantic_revision"], str)
        or not isinstance(recovery_point["schema_revision"], str)
        or recovery_point["secret_disposition"] != SECRET_DISPOSITION
    ):
        raise LifecycleError("cold_recovery_point_invalid", "cold copy recovery_point fields are invalid")
    _require_valid_matching_installer(recovery_point["matching_installer_requirement"])


def _require_archive_components(manifest: dict, names: list[str]) -> None:
    records = manifest["entries"]
    if manifest["schema"] == SCHEMA and (
        manifest.get("public_connectivity") != CONNECTOR_POLICY
        or any(_connector_secret(name) for name in records)
    ):
        raise LifecycleError("cold_secret_policy_invalid", "new cold copies must exclude the exact connector secret directory")
    if "recovery_point" in manifest:
        _require_valid_recovery_point(manifest["recovery_point"])
    if (
        set(names) != set(records) | {MANIFEST}
        or any(f"{root}/" not in records for root in COMPONENTS)
        or not _REQUIRED_FILES.issubset(records)
    ):
        raise LifecycleError("cold_incomplete", "cold copy component set is incomplete")


def _is_excluded(relative: str, exclude_entry: Callable[[str], bool] | None) -> bool:
    if exclude_entry is None:
        return False
    normalized = relative.replace("\\", "/")
    if normalized.startswith("data/") or normalized in _REQUIRED_FILES:
        return False
    return exclude_entry(normalized)


def _scan(
    roots: Mapping[str, Path],
    *,
    exclude_entry: Callable[[str], bool] | None = None,
) -> dict[str, Path | None]:
    found: dict[str, Path | None] = {}
    for prefix, root in roots.items():
        reject_reparse_components(root)
        if not root.is_dir():
            raise LifecycleError("cold_source_missing", "a required cold copy directory is missing")
        found[f"{prefix}/"] = None
        for parent, directories, files in os.walk(root, onerror=_raise_walk_error):
            # Exclude this entire dedicated authority, including unknown future
            # pending/previous names. No filename heuristic may hide DB secrets.
            kept_dirs: list[str] = []
            for name in directories:
                rel_dir = f"{prefix}/{(Path(parent) / name).relative_to(root).as_posix()}"
                if _connector_secret(rel_dir) or _is_excluded(f"{rel_dir}/", exclude_entry):
                    continue
                kept_dirs.append(name)
            directories[:] = kept_dirs
            for name in sorted(directories + files):
                path = Path(parent) / name
                reject_reparse_components(path)
                mode = path.lstat().st_mode
                relative = f"{prefix}/{path.relative_to(root).as_posix()}"
                if _connector_secret(relative):
                    raise LifecycleError("cold_secret_shape_invalid", "connector secret authority must be a directory")
                if stat.S_ISDIR(mode):
                    found[f"{relative}/"] = None
                elif stat.S_ISREG(mode):
                    if _is_excluded(relative, exclude_entry):
                        continue
                    found[relative] = path
                else:
                    raise LifecycleError("cold_source_invalid", "cold copy contains a non-regular file")
    return dict(sorted(found.items()))


def _connector_secret(name: str) -> bool:
    # Windows is case-insensitive. Archive policy must not admit spelling aliases.
    normalized = name.replace("\\", "/").rstrip("/").casefold()
    return normalized == CONNECTOR_SECRET_ROOT or normalized.startswith(CONNECTOR_SECRET_ROOT + "/")


def _raise_walk_error(error: OSError) -> None:
    raise error


def _copy_file(archive: zipfile.ZipFile, name: str, path: Path) -> dict[str, object]:
    reject_reparse_components(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
        before = os.fstat(source.fileno())
        while chunk := source.read(_CHUNK):
            target.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        if _file_identity(before) != _file_identity(os.fstat(source.fileno())):
            raise LifecycleError("cold_source_changed", "source file changed while being copied")
    return {"size": size, "sha256": digest.hexdigest()}


def _file_identity(observed: os.stat_result) -> tuple[int, ...]:
    return observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns


def _digest_file(path: Path) -> dict[str, object]:
    reject_reparse_components(path)
    with path.open("rb") as source:
        return _digest(source)


def _digest(source: BinaryIO) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def _summary(manifest: dict[str, object]) -> dict[str, object]:
    files = [record for record in manifest["entries"].values() if record is not None]
    result: dict[str, object] = {
        "files": len(files),
        "bytes": sum(record["size"] for record in files),
        "identity": manifest["identity"],
        "schema": manifest["schema"],
        "public_connectivity": manifest.get("public_connectivity", {"credentials": "legacy_unspecified"}),
    }
    if "recovery_point" in manifest:
        result["recovery_point"] = manifest["recovery_point"]
    return result
