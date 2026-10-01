"""A sealed, read-verifiable retention copy; it has no installation/restore writer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import BinaryIO

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components

SCHEMA = "ticketbox-beta-cold-copy-v1"
MANIFEST = "COLD_COPY.json"
COMPONENTS = frozenset({"program", "machine", "data/pgdata", "data/attachments", "data/app"})
_REQUIRED_FILES = frozenset({
    "data/pgdata/PG_VERSION", "data/pgdata/global/pg_control", "data/app/.env", "machine/installation.json",
    "machine/secrets/postgres.password", "machine/secrets/ticketbox_migrator.password",
    "machine/secrets/ticketbox_runtime.password", "machine/secrets/pgpass",
})
_CHUNK = 1024 * 1024


def write_archive(
    output: BinaryIO,
    roots: Mapping[str, Path],
    identity: dict[str, object],
    require_stopped: Callable[[], None],
) -> dict[str, object]:
    """Keep the output incomplete until the original tree and stop state agree."""
    if set(roots) != COMPONENTS:
        raise LifecycleError("cold_sources_invalid", "cold copy source set is incomplete")
    require_stopped()
    sources = _scan(roots)
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
        if sources != _scan(roots):
            raise LifecycleError("cold_source_changed", "source file set changed during cold copy")
        require_stopped()
        manifest = {"schema": SCHEMA, "complete": True, "identity": identity, "entries": records}
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
        or manifest.get("schema") != SCHEMA
        or manifest.get("complete") is not True
        or not isinstance(manifest.get("identity"), dict)
        or not isinstance(manifest.get("entries"), dict)
    ):
        raise LifecycleError("cold_incomplete", "cold copy completion manifest is invalid")
    records = manifest["entries"]
    if (
        set(names) != set(records) | {MANIFEST}
        or any(f"{root}/" not in records for root in COMPONENTS)
        or not _REQUIRED_FILES.issubset(records)
    ):
        raise LifecycleError("cold_incomplete", "cold copy component set is incomplete")
    return manifest


def _scan(roots: Mapping[str, Path]) -> dict[str, Path | None]:
    found: dict[str, Path | None] = {}
    for prefix, root in roots.items():
        reject_reparse_components(root)
        if not root.is_dir():
            raise LifecycleError("cold_source_missing", "a required cold copy directory is missing")
        found[f"{prefix}/"] = None
        for parent, directories, files in os.walk(root, onerror=_raise_walk_error):
            for name in sorted(directories + files):
                path = Path(parent) / name
                reject_reparse_components(path)
                mode = path.lstat().st_mode
                relative = f"{prefix}/{path.relative_to(root).as_posix()}"
                if stat.S_ISDIR(mode):
                    found[f"{relative}/"] = None
                elif stat.S_ISREG(mode):
                    found[relative] = path
                else:
                    raise LifecycleError("cold_source_invalid", "cold copy contains a non-regular file")
    return dict(sorted(found.items()))


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
    return {"files": len(files), "bytes": sum(record["size"] for record in files), "identity": manifest["identity"]}
