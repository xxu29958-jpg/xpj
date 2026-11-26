"""Read a trusted cold copy and copy only data into a new, private candidate.

Archived executables, service bindings and Windows credentials are never adopted.
The caller owns the lifecycle lock and has already established the empty target.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from ticketbox_lifecycle.domain.cold_copy import cold_copy_backup_id
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.cold_archive import _read_manifest, verify_archive
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import InstallRequest

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.IGNORECASE)


def _require_member_path(entry: zipfile.ZipInfo) -> str:
    name = entry.filename.rstrip("/")
    parts = PurePosixPath(name).parts
    mode = entry.external_attr >> 16
    if (
        not parts or name != "/".join(parts) or name.startswith("/")
        or "\\" in name or ":" in name or any(ord(char) < 32 for char in name)
        or any(part in {".", ".."} or part.endswith((" ", ".")) or _RESERVED.fullmatch(part) for part in parts)
        or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
    ):
        raise LifecycleError("restore_archive_path_invalid", "cold copy contains an unsafe Windows member")
    return name


def _safe_members(archive: zipfile.ZipFile) -> None:
    seen: set[str] = set()
    for entry in archive.infolist():
        name = _require_member_path(entry)
        if name.casefold() in seen:
            raise LifecycleError("restore_archive_path_invalid", "cold copy contains an unsafe Windows alias")
        seen.add(name.casefold())
    files = {entry.filename.casefold() for entry in archive.infolist() if not entry.is_dir()}
    for entry in archive.infolist():
        parents = PurePosixPath(entry.filename).parents
        if any(str(parent).casefold() in files for parent in parents):
            raise LifecycleError("restore_archive_path_invalid", "cold copy file and directory paths collide")


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _upgrade_chain_reaches_origin(
    origin: dict[str, object],
    current: dict[str, object],
    upgrades: list[dict[str, object]],
) -> bool:
    origin_release = origin.get("target_release_id") or origin.get("release_id")
    if not isinstance(origin_release, str) or not origin_release:
        return False
    by_target: dict[str, dict[str, object]] = {}
    for record in upgrades:
        target = record.get("target_release_id")
        previous = record.get("previous_release_id")
        if not isinstance(target, str) or not isinstance(previous, str) or target in by_target:
            return False
        by_target[target] = record
    visited: set[str] = set()
    cursor: dict[str, object] | None = current
    while cursor is not None:
        target = cursor.get("target_release_id")
        previous = cursor.get("previous_release_id")
        if not isinstance(target, str) or not isinstance(previous, str) or not previous or target in visited:
            return False
        visited.add(target)
        if previous == origin_release:
            return True
        cursor = by_target.get(previous)
    return False


class ColdRestoreSource:
    """An open, fully checked source; retain the same handle through extraction."""

    def __init__(self, stream: BinaryIO, digest: str, request: InstallRequest) -> None:
        if _DIGEST.fullmatch(digest) is None:
            raise LifecycleError("restore_digest_required", "supply the trusted backup SHA-256")
        stream.seek(0)
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise LifecycleError("restore_digest_mismatch", "backup SHA-256 does not match the selected recovery point")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            _safe_members(archive)
            manifest = _read_manifest(archive)
            self.source_operation_id = self._require_identity(archive, manifest, request)
            self._require_program(archive, manifest, request)
        stream.seek(0)
        verify_archive(stream)
        self.stream = stream
        self.digest = digest
        self.manifest = manifest
        self.identity = dict(manifest["identity"])
        self.backup_id = cold_copy_backup_id(digest)

    @staticmethod
    def _require_identity(archive: zipfile.ZipFile, manifest: dict, request: InstallRequest) -> str:
        identity = manifest["identity"]
        binding = json.loads(archive.read("machine/installation.json"))
        if (
            not _uuid(identity.get("dataset_id")) or not _uuid(identity.get("install_id"))
            or type(identity.get("restore_epoch")) is not int or identity["restore_epoch"] < 0
            or identity.get("postgres_major") != request.postgres_major
            or identity.get("schema_revision") != request.schema_revision
            or identity.get("release_id") != request.target_release_id
            or binding.get("schema") != "ticketbox-installed-instance-v1"
            or any(binding.get(field) != identity[field] for field in ("dataset_id", "install_id"))
            or binding.get("expected_restore_epoch") != identity["restore_epoch"]
            or binding.get("release_manifest_sha256") != identity.get("release_manifest_sha256")
        ):
            raise LifecycleError("restore_identity_mismatch", "cold copy is outside the same-environment profile")
        ColdRestoreSource._require_stopped_cluster(archive, manifest["entries"], request.postgres_major)
        return ColdRestoreSource._committed_owner_operation(archive, manifest)

    @staticmethod
    def _require_stopped_cluster(archive: zipfile.ZipFile, entries: dict, major: int) -> None:
        if (
            "data/pgdata/postmaster.pid" in entries
            or "machine/operations/active.json" in entries
            or any(name.startswith("data/pgdata/pg_tblspc/") and name != "data/pgdata/pg_tblspc/" for name in entries)
            or archive.read("data/pgdata/PG_VERSION").decode("ascii").strip() != str(major)
        ):
            raise LifecycleError("restore_cluster_unsupported", "restore requires a stopped local cluster without tablespaces")
    @staticmethod
    def _committed_owner_operation(archive: zipfile.ZipFile, manifest: dict) -> str:
        identity = manifest["identity"]
        history = [
            json.loads(archive.read(name))
            for name in manifest["entries"]
            if name.startswith("machine/operations/history/") and name.endswith(".json")
        ]
        committed = [
            record
            for record in history
            if isinstance(record, dict)
            and record.get("schema") == "ticketbox-lifecycle-operation-v2"
            and record.get("phase") == "committed"
            and record.get("install_id") == identity["install_id"]
            and record.get("dataset_id") == identity["dataset_id"]
        ]
        origins = [record for record in committed if record.get("kind") in {"install", "restore"}]
        if len(origins) != 1 or not isinstance(origins[0].get("operation_id"), str) or not origins[0]["operation_id"]:
            raise LifecycleError(
                "restore_recovery_material_missing",
                "cold copy lacks its exact committed owner recovery context",
            )
        origin = origins[0]
        if origin.get("release_manifest_sha256") == identity["release_manifest_sha256"]:
            return origin["operation_id"]
        upgrades = [
            record
            for record in committed
            if record.get("kind") == "upgrade"
            and record.get("expected_restore_epoch") == identity["restore_epoch"]
        ]
        target_upgrades = [
            record
            for record in upgrades
            if record.get("release_manifest_sha256") == identity["release_manifest_sha256"]
            and record.get("target_release_id") == identity["release_id"]
        ]
        if len(target_upgrades) != 1 or not _upgrade_chain_reaches_origin(origin, target_upgrades[0], upgrades):
            raise LifecycleError(
                "restore_recovery_material_missing",
                "cold copy lacks committed upgrade provenance for its current release",
            )
        return origin["operation_id"]

    def recovery_secret(self) -> str:
        """Use the existing machine bootstrap root, never OS identity as business authority."""
        with zipfile.ZipFile(self.stream) as archive:
            root = archive.read("machine/secrets/postgres.password").decode("ascii").strip()
        message = ("ticketbox/fresh-owner/v1\0" + self.source_operation_id + "\0" + self.identity["install_id"]).encode()
        return hmac.new(root.encode(), message, hashlib.sha256).hexdigest()

    @staticmethod
    def _require_program(archive: zipfile.ZipFile, manifest: dict, request: InstallRequest) -> None:
        prefix = "program/"
        name = f"program/releases/{request.target_release_id}/release-manifest.json"
        try:
            raw = archive.read(name)
            release = json.loads(raw)
            inventory = release["immutable_payload"]["files"]
            expected = {prefix + item["path"]: {"size": item["size"], "sha256": item["sha256"]} for item in inventory}
        except (KeyError, TypeError, ValueError) as exc:
            raise LifecycleError("restore_program_mismatch", "cold copy program inventory is incomplete") from exc
        entries = manifest["entries"]
        actual = {key: value for key, value in entries.items() if key.startswith(prefix) and value is not None and key != name}
        if (
            hashlib.sha256(raw).hexdigest() != manifest["identity"]["release_manifest_sha256"]
            or release.get("max_schema_revision") != request.schema_revision
            or release.get("min_semantic_revision") != request.semantic_revision
            or release.get("release_id") != request.target_release_id
            or actual != expected
        ):
            raise LifecycleError("restore_program_mismatch", "cold copy program, schema or semantics are incompatible")
        # A physical PG copy is admitted only with the identical shipped PG tree.
        archived_pg = {key[len(prefix):]: value for key, value in actual.items() if key.startswith("program/postgresql/")}
        ColdRestoreSource._require_postgres_program(archived_pg, request)

    @staticmethod
    def _require_postgres_program(archived_pg: dict, request: InstallRequest) -> None:
        pg_root = Path(request.app_dir) / "postgresql"
        current_pg = {}
        for path in pg_root.rglob("*"):
            reject_reparse_components(path)
            if path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                current_pg[path.relative_to(request.app_dir).as_posix()] = {"size": path.stat().st_size, "sha256": digest}
        if not archived_pg or current_pg != archived_pg:
            raise LifecycleError("restore_postgres_mismatch", "restore requires the identical trusted PostgreSQL program")

    def extract_data(self, data_root: Path, *, make_private: Callable[[Path], None] | None = None) -> None:
        """Never overwrite a candidate, copy a binding, or launch an archived tool."""
        reject_reparse_components(data_root)
        if data_root.exists():
            raise LifecycleError("restore_target_exists", "restore requires a new data directory")
        data_root.mkdir()
        if make_private is not None:
            make_private(data_root)
        self.stream.seek(0)
        with zipfile.ZipFile(self.stream) as archive:
            for name, record in self.manifest["entries"].items():
                if not name.startswith("data/"):
                    continue
                target = data_root / name[len("data/"):]
                if record is None:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                with target.open("rb") as copied:
                    digest = hashlib.file_digest(copied, "sha256").hexdigest()
                if target.stat().st_size != record["size"] or digest != record["sha256"]:
                    raise LifecycleError("restore_copy_changed", "isolated copy failed readback; keep source and failed candidate")
        # Re-read the source after copying. Failure keeps the candidate fenced.
        self.stream.seek(0)
        if hashlib.file_digest(self.stream, "sha256").hexdigest() != self.digest:
            raise LifecycleError("restore_source_changed", "source changed during copying; candidate cannot be published")

    def restore_shared_program_files(
        self,
        app_dir: Path,
        *,
        temp_root: Path,
        publish_acl: Callable[..., None] | None = None,
        verify_acl: Callable[..., None] | None = None,
    ) -> list[str]:
        """Restore non-release shared program files from this verified archive into app_dir."""
        reject_reparse_components(app_dir)
        reject_reparse_components(temp_root)
        app_drive = os.path.splitdrive(os.path.abspath(os.fspath(app_dir)))[0].casefold()
        tmp_drive = os.path.splitdrive(os.path.abspath(os.fspath(temp_root)))[0].casefold()
        if app_drive != tmp_drive:
            raise LifecycleError(
                "rollback_temp_cross_volume",
                "shared program restore staging directory must reside on the same volume as app_dir",
            )
        temp_root.mkdir(parents=True, exist_ok=True)
        shared_entries = {
            name[len("program/"):]: record
            for name, record in self.manifest["entries"].items()
            if name.startswith("program/")
            and record is not None
            and not name.startswith("program/releases/")
            and not name.startswith("program/postgresql/")
        }
        expected_lifecycle = {
            rel[len("bin/lifecycle/"):].casefold()
            for rel in shared_entries
            if rel.casefold().startswith("bin/lifecycle/")
        }
        restored: list[str] = []
        self.stream.seek(0)
        with zipfile.ZipFile(self.stream) as archive:
            for rel, record in sorted(shared_entries.items(), key=lambda pair: pair[0].casefold()):
                dest = app_dir / Path(rel)
                reject_reparse_components(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_file() and dest.stat().st_size == record["size"]:
                    with dest.open("rb") as existing_fh:
                        existing_sha = hashlib.file_digest(existing_fh, "sha256").hexdigest()
                    if existing_sha == record["sha256"]:
                        if publish_acl is not None:
                            publish_acl(dest, is_dir=False)
                        if verify_acl is not None:
                            verify_acl(dest, is_dir=False)
                        continue
                fd, tmp_name = tempfile.mkstemp(prefix=dest.name, suffix=".tmp", dir=str(temp_root))
                tmp_path = Path(tmp_name)
                try:
                    with os.fdopen(fd, "wb") as out, archive.open("program/" + rel) as inp:
                        shutil.copyfileobj(inp, out, length=1024 * 1024)
                        out.flush()
                        os.fsync(out.fileno())
                    with tmp_path.open("rb") as check_fh:
                        observed_sha = hashlib.file_digest(check_fh, "sha256").hexdigest()
                    if tmp_path.stat().st_size != record["size"] or observed_sha != record["sha256"]:
                        raise LifecycleError(
                            "rollback_shared_payload_corrupt",
                            f"restored shared program file checksum mismatch: {rel}",
                        )
                    if publish_acl is not None:
                        publish_acl(tmp_path, is_dir=False)
                    os.replace(tmp_path, dest)
                except BaseException:
                    if tmp_path.exists():
                        tmp_path.unlink()
                    raise
                if verify_acl is not None:
                    verify_acl(dest, is_dir=False)
                restored.append(rel)

        lifecycle_dir = app_dir / "bin" / "lifecycle"
        if lifecycle_dir.is_dir():
            reject_reparse_components(lifecycle_dir)
            for root_dir, dirs, files in os.walk(lifecycle_dir, topdown=False, followlinks=False):
                root_path = Path(root_dir)
                for filename in files:
                    candidate = root_path / filename
                    rel_lc = candidate.relative_to(lifecycle_dir).as_posix().casefold()
                    if rel_lc not in expected_lifecycle:
                        reject_reparse_components(candidate)
                        candidate.unlink()
                for dirname in dirs:
                    candidate = root_path / dirname
                    reject_reparse_components(candidate)
                    if not any(candidate.iterdir()):
                        candidate.rmdir()

        self.stream.seek(0)
        if hashlib.file_digest(self.stream, "sha256").hexdigest() != self.digest:
            raise LifecycleError("restore_source_changed", "cold copy changed during shared payload restore")
        return restored
