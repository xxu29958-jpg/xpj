"""Offline existing-dataset upgrade on a caller-owned PostgreSQL transaction."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.database._database_generation_executor import (
    DatabaseGenerationExecutionError,
    validate_generation_operation_id,
)
from app.database._database_generation_program import (
    BASE_SOURCE,
    DatabaseGenerationProgram,
    DatabaseGenerationProgramError,
    DatabaseGenerationRevision,
    load_installed_database_generation_program,
)
from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
)

RESULT_SCHEMA = "ticketbox-existing-dataset-upgrade-result-v1"
_ALEMBIC_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000
_ORIGINAL_RECEIPT_OPERATIONS = frozenset({
    "attach_original",
    "verify_original",
    "replenish_original",
    "retry_original_cleanup",
    "cancel_original_cleanup",
})
_COLD_COPY_SCHEMA = "ticketbox-beta-cold-copy-v2"
_COLD_COPY_COMPONENTS = frozenset({"program", "machine", "data/pgdata", "data/attachments", "data/app"})
_COLD_COPY_CONNECTOR_SECRET_ROOT = "machine/connectors/cloudflare/secrets"
_COLD_COPY_CONNECTOR_POLICY = {
    "excluded_directory": _COLD_COPY_CONNECTOR_SECRET_ROOT,
    "credentials": "not_backed_up",
    "after_restore": "configure_again",
}
_COLD_COPY_REQUIRED_FILES = frozenset({
    "data/pgdata/PG_VERSION",
    "data/pgdata/global/pg_control",
    "data/app/.env",
    "machine/installation.json",
    "machine/secrets/postgres.password",
    "machine/secrets/ticketbox_migrator.password",
    "machine/secrets/ticketbox_runtime.password",
    "machine/secrets/pgpass",
})
_COLD_COPY_SECRET_DISPOSITION = {
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
_WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.IGNORECASE)
_WINDOWS_REPARSE_ATTRIBUTE = 0x400


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_hex_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


def _require_valid_matching_installer(installer: object) -> None:
    if not isinstance(installer, dict) or set(installer) != _MATCHING_INSTALLER_KEYS:
        raise ExistingDatasetUpgradeError("pre-upgrade backup matching_installer_requirement is invalid")
    installer_pg = installer["postgres_major"]
    if (
        not isinstance(installer["release_id"], str)
        or not isinstance(installer["release_manifest_sha256"], str)
        or (installer_pg is not None and not _is_positive_int(installer_pg))
        or not _is_nonempty_str(installer["verify_command"])
    ):
        raise ExistingDatasetUpgradeError("pre-upgrade backup matching_installer_requirement is invalid")


def _require_valid_recovery_point(recovery_point: object) -> None:
    if not isinstance(recovery_point, dict) or set(recovery_point) != _RECOVERY_POINT_KEYS:
        raise ExistingDatasetUpgradeError("pre-upgrade backup recovery_point metadata is invalid")
    if (
        not _is_nonempty_str(recovery_point["cutoff_utc"])
        or not _is_nonempty_str(recovery_point["api_version"])
        or not isinstance(recovery_point["semantic_revision"], str)
        or not isinstance(recovery_point["schema_revision"], str)
        or recovery_point["secret_disposition"] != _COLD_COPY_SECRET_DISPOSITION
    ):
        raise ExistingDatasetUpgradeError("pre-upgrade backup recovery_point fields are invalid")
    _require_valid_matching_installer(recovery_point["matching_installer_requirement"])


def _reject_reparse_path(path: Path) -> None:
    current = Path(os.path.abspath(os.fspath(path)))
    for candidate in (*reversed(current.parents), current):
        if not os.path.lexists(candidate):
            continue
        info = os.lstat(candidate)
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _WINDOWS_REPARSE_ATTRIBUTE):
            raise ExistingDatasetUpgradeError(f"refusing reparse point in upgrade path: {candidate}")


def _infer_frozen_app_dir() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    parents = exe.parents
    if len(parents) >= 4 and parents[2].name.casefold() == "releases":
        return parents[3]
    return None


class ExistingDatasetUpgradeError(RuntimeError):
    """The offline existing-dataset upgrade could not be proven safe."""


def _canonical_uuid(value: str, *, label: str) -> str:
    try:
        canonical = str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExistingDatasetUpgradeError(f"{label} is not a UUID") from exc
    if value != canonical:
        raise ExistingDatasetUpgradeError(f"{label} is not canonical")
    return canonical


def _require_revision(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _ALEMBIC_REVISION.fullmatch(value) is None:
        raise ExistingDatasetUpgradeError(f"{label} is not an Alembic revision")
    return value


def _postcondition(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ExistingDatasetUpgradeError(f"cannot parse migration {path.name}") from exc
    return (
        "assert_postcondition"
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "assert_postcondition"
            for node in tree.body
        )
        else None
    )


def _load_source_generation_program() -> DatabaseGenerationProgram:
    root = Path(__file__).resolve().parents[2].resolve(strict=True)
    versions_root = (root / "migrations" / "versions").resolve(strict=True)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    heads = tuple(scripts.get_heads())
    bases = tuple(scripts.get_bases())
    if len(heads) != 1 or len(bases) != 1:
        raise ExistingDatasetUpgradeError("source migrations do not have one base and head")
    target = heads[0]
    forward = tuple(reversed(tuple(scripts.iterate_revisions(target, "base"))))
    previous: str | None = None
    revisions: list[DatabaseGenerationRevision] = []
    digest = hashlib.sha256()
    for item in forward:
        module_path = Path(str(item.path)).resolve(strict=True)
        if module_path.parent != versions_root or item.down_revision != previous or item.dependencies is not None:
            raise ExistingDatasetUpgradeError("source migrations are not one linear chain")
        raw = module_path.read_bytes()
        module_sha = hashlib.sha256(raw).hexdigest()
        digest.update(f"{item.revision}:{module_sha}\n".encode("ascii"))
        revisions.append(
            DatabaseGenerationRevision(
                revision=str(item.revision),
                down_revision=previous,
                module_path=module_path,
                module_sha256=module_sha,
                postcondition=_postcondition(module_path),
            )
        )
        previous = str(item.revision)
    if not revisions or previous != target or revisions[-1].postcondition != "assert_postcondition":
        raise ExistingDatasetUpgradeError("source migrations do not end in a qualified head")
    return DatabaseGenerationProgram(
        path=root / "alembic.ini",
        payload_sha256=digest.hexdigest(),
        source_revision=BASE_SOURCE,
        target_revision=target,
        revisions=tuple(revisions),
    )


def _resolve_program(program: DatabaseGenerationProgram | None) -> DatabaseGenerationProgram:
    if program is not None:
        return program
    if getattr(sys, "frozen", False):
        try:
            return load_installed_database_generation_program()
        except DatabaseGenerationProgramError as exc:
            raise ExistingDatasetUpgradeError(str(exc)) from exc
    return _load_source_generation_program()


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise ExistingDatasetUpgradeError(f"{label} must be a 64-char lowercase hex sha256")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_connector_secret_entry(name: str) -> bool:
    normalized = name.replace("\\", "/").rstrip("/").casefold()
    return (
        normalized == _COLD_COPY_CONNECTOR_SECRET_ROOT
        or normalized.startswith(_COLD_COPY_CONNECTOR_SECRET_ROOT + "/")
    )


def _is_safe_member_part(part: str) -> bool:
    return (
        part not in {".", ".."}
        and not part.endswith((" ", "."))
        and _WINDOWS_RESERVED.fullmatch(part) is None
    )


def _has_safe_member_name(name: str, parts: tuple[str, ...]) -> bool:
    return (
        bool(parts)
        and name == "/".join(parts)
        and not name.startswith("/")
        and "\\" not in name
        and ":" not in name
        and all(ord(char) >= 32 for char in name)
    )


def _is_safe_archive_entry(entry: zipfile.ZipInfo) -> bool:
    name = entry.filename.rstrip("/")
    parts = PurePosixPath(name).parts
    mode = entry.external_attr >> 16
    return (
        _has_safe_member_name(name, parts)
        and all(_is_safe_member_part(part) for part in parts)
        and stat.S_IFMT(mode) in {0, stat.S_IFREG, stat.S_IFDIR}
    )


def _require_safe_archive_members(archive: zipfile.ZipFile) -> None:
    seen: set[str] = set()
    infos = archive.infolist()
    for entry in infos:
        if not _is_safe_archive_entry(entry):
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive contains an unsafe member path")
        folded = entry.filename.rstrip("/").casefold()
        if folded in seen:
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive contains an unsafe member alias")
        seen.add(folded)
    files = {entry.filename.casefold() for entry in infos if not entry.is_dir()}
    for entry in infos:
        if any(str(parent).casefold() in files for parent in PurePosixPath(entry.filename).parents):
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive file and directory paths collide")


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


class _VerifiedBackupArchive:
    def __init__(
        self,
        archive_path: Path,
        expected_sha256: str,
        *,
        dataset_id: str,
        installation_id: str,
        expected_restore_epoch: int,
        source_revision: str,
        app_dir: Path | None = None,
    ) -> None:
        self._path = archive_path
        self._expected_sha256 = expected_sha256
        self._dataset_id = dataset_id
        self._installation_id = installation_id
        self._expected_restore_epoch = expected_restore_epoch
        self._source_revision = source_revision
        self._app_dir = app_dir if app_dir is not None else _infer_frozen_app_dir()
        self._stream: BinaryIO | None = None
        self._zip: zipfile.ZipFile | None = None
        self._entries: dict[str, object] = {}
        self._verified_members: dict[str, tuple[int, str]] = {}

    def __enter__(self) -> _VerifiedBackupArchive:
        if not self._path.is_absolute() or not self._path.is_file():
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive is unavailable")
        try:
            stream = self._path.open("rb")
        except OSError as exc:
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive cannot be opened") from exc
        self._stream = stream
        try:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != self._expected_sha256:
                raise ExistingDatasetUpgradeError("pre-upgrade backup archive digest mismatch")
            stream.seek(0)
            archive = zipfile.ZipFile(stream, "r")
            self._zip = archive
            _require_safe_archive_members(archive)
            names = archive.namelist()
            if len(names) != len(set(names)) or "COLD_COPY.json" not in names:
                raise ExistingDatasetUpgradeError("pre-upgrade backup archive has no unique completion manifest")
            manifest = json.loads(archive.read("COLD_COPY.json").decode("utf-8"))
            self._validate_restorable_structure(manifest, names)
        except ExistingDatasetUpgradeError:
            self._close()
            raise
        except (OSError, KeyError, UnicodeError, ValueError, zipfile.BadZipFile, zlib.error) as exc:
            self._close()
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive manifest is invalid") from exc
        return self

    def __exit__(self, *_exc: object) -> None:
        self._close()

    def _close(self) -> None:
        if self._zip is not None:
            try:
                self._zip.close()
            finally:
                self._zip = None
        if self._stream is not None:
            try:
                self._stream.close()
            finally:
                self._stream = None

    def _read_verified_member_bytes(self, relative: str) -> bytes:
        assert self._zip is not None
        record = self._entries.get(relative)
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or _SHA256_HEX.fullmatch(record["sha256"]) is None
            or type(record.get("size")) is not int
            or record["size"] < 0
        ):
            raise ExistingDatasetUpgradeError(f"pre-upgrade backup is missing required member: {relative}")
        try:
            payload = self._zip.read(relative)
        except (OSError, KeyError, zipfile.BadZipFile, zlib.error) as exc:
            raise ExistingDatasetUpgradeError(
                f"pre-upgrade backup member is unreadable: {relative}"
            ) from exc
        actual_sha = hashlib.sha256(payload).hexdigest()
        if len(payload) != record["size"] or actual_sha != record["sha256"]:
            raise ExistingDatasetUpgradeError(
                f"pre-upgrade backup member checksum mismatch: {relative}"
            )
        self._verified_members[relative] = (len(payload), actual_sha)
        return payload

    def _validate_manifest_envelope(self, manifest: object) -> dict[str, object]:
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema") != _COLD_COPY_SCHEMA
            or manifest.get("complete") is not True
            or manifest.get("public_connectivity") != _COLD_COPY_CONNECTOR_POLICY
            or not isinstance(manifest.get("identity"), dict)
            or not isinstance(manifest.get("entries"), dict)
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive is not a valid cold-copy-v2 archive")
        if "recovery_point" in manifest:
            _require_valid_recovery_point(manifest["recovery_point"])
        return manifest

    @staticmethod
    def _validate_archive_entry_layout(names: list[str], entries: dict[str, object]) -> None:
        has_nested_tblspc = any(
            name.startswith("data/pgdata/pg_tblspc/") and name != "data/pgdata/pg_tblspc/"
            for name in entries
        )
        if (
            set(names) != set(entries) | {"COLD_COPY.json"}
            or any(f"{root}/" not in entries for root in _COLD_COPY_COMPONENTS)
            or not _COLD_COPY_REQUIRED_FILES.issubset(entries)
            or any(_is_connector_secret_entry(name) for name in entries)
            or "data/pgdata/postmaster.pid" in entries
            or "machine/operations/active.json" in entries
            or has_nested_tblspc
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive is missing required recovery components")

    def _validate_archive_identity(self, identity: dict[str, object]) -> tuple[str, str, int]:
        release_id = identity.get("release_id")
        release_manifest_sha = identity.get("release_manifest_sha256")
        pg_major = identity.get("postgres_major")
        archive_epoch = identity.get("restore_epoch")
        if (
            identity.get("install_id") != self._installation_id
            or identity.get("dataset_id") != self._dataset_id
            or type(archive_epoch) is not int
            or archive_epoch != self._expected_restore_epoch
            or identity.get("schema_revision") != self._source_revision
            or not _is_nonempty_str(release_id)
            or not _is_hex_sha256(release_manifest_sha)
            or not _is_positive_int(pg_major)
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade backup archive identity does not match target dataset")
        assert isinstance(release_id, str)
        assert isinstance(release_manifest_sha, str)
        assert isinstance(pg_major, int)
        return release_id, release_manifest_sha, pg_major

    def _validate_installation_binding(
        self,
        payload: bytes,
        *,
        release_id: str,
        release_manifest_sha: str,
    ) -> None:
        binding = json.loads(payload.decode("utf-8"))
        if not isinstance(binding, dict):
            raise ExistingDatasetUpgradeError("pre-upgrade backup installation.json disagrees with identity")
        binding_epoch = binding.get("expected_restore_epoch")
        if (
            binding.get("schema") != "ticketbox-installed-instance-v1"
            or binding.get("install_id") != self._installation_id
            or binding.get("dataset_id") != self._dataset_id
            or type(binding_epoch) is not int
            or binding_epoch != self._expected_restore_epoch
            or binding.get("active_release_id") != release_id
            or binding.get("release_manifest_sha256") != release_manifest_sha
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade backup installation.json disagrees with identity")

    def _validate_required_files(
        self,
        *,
        pg_major: int,
        release_id: str,
        release_manifest_sha: str,
    ) -> None:
        for required in sorted(_COLD_COPY_REQUIRED_FILES):
            payload = self._read_verified_member_bytes(required)
            if required == "data/pgdata/PG_VERSION" and payload.decode("ascii").strip() != str(pg_major):
                raise ExistingDatasetUpgradeError("pre-upgrade backup PG_VERSION disagrees with archive identity")
            if required == "machine/installation.json":
                self._validate_installation_binding(
                    payload,
                    release_id=release_id,
                    release_manifest_sha=release_manifest_sha,
                )

    def _validate_restorable_structure(self, manifest: object, names: list[str]) -> None:
        valid_manifest = self._validate_manifest_envelope(manifest)
        entries = valid_manifest["entries"]
        assert isinstance(entries, dict)
        self._entries = entries
        self._validate_archive_entry_layout(names, entries)
        self._verify_all_members()
        identity = valid_manifest["identity"]
        assert isinstance(identity, dict)
        release_id, release_manifest_sha, pg_major = self._validate_archive_identity(identity)
        self._validate_required_files(
            pg_major=pg_major,
            release_id=release_id,
            release_manifest_sha=release_manifest_sha,
        )
        self._validate_program_inventory(release_id, release_manifest_sha)
        self._validate_recovery_history(identity)

    def _verify_all_members(self) -> None:
        assert self._zip is not None
        for name, expected in self._entries.items():
            if expected is None:
                if not name.endswith("/") or self._zip.getinfo(name).file_size != 0:
                    raise ExistingDatasetUpgradeError(
                        f"pre-upgrade backup directory entry is invalid: {name}"
                    )
                continue
            if (
                not isinstance(expected, dict)
                or set(expected) != {"size", "sha256"}
                or not _is_nonnegative_int(expected["size"])
                or not _is_hex_sha256(expected["sha256"])
            ):
                raise ExistingDatasetUpgradeError(f"pre-upgrade backup entry metadata is invalid: {name}")
            observed_size, observed_sha = self._member_digest(name)
            if observed_size != expected["size"] or observed_sha != expected["sha256"]:
                raise ExistingDatasetUpgradeError(
                    f"pre-upgrade backup member checksum mismatch: {name}"
                )

    @staticmethod
    def _is_valid_inventory_item(item: object) -> bool:
        return (
            isinstance(item, dict)
            and _is_nonempty_str(item.get("path"))
            and _is_nonnegative_int(item.get("size"))
            and _is_hex_sha256(item.get("sha256"))
        )

    @classmethod
    def _parse_program_inventory(
        cls,
        release_bytes: bytes,
    ) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        try:
            release = json.loads(release_bytes.decode("utf-8"))
            inventory = release["immutable_payload"]["files"]
            if not isinstance(inventory, list) or not inventory:
                raise ValueError("empty inventory")
            expected: dict[str, dict[str, object]] = {}
            for item in inventory:
                if not cls._is_valid_inventory_item(item):
                    raise ValueError("invalid inventory entry")
                key = "program/" + item["path"]
                if key in expected:
                    raise ValueError("duplicate inventory entry")
                expected[key] = {"size": item["size"], "sha256": item["sha256"]}
        except (KeyError, TypeError, ValueError) as exc:
            raise ExistingDatasetUpgradeError("pre-upgrade backup program inventory is incomplete") from exc
        return release, expected

    def _validate_program_inventory(self, release_id: str, release_manifest_sha: str) -> None:
        manifest_member = f"program/releases/{release_id}/release-manifest.json"
        release_bytes = self._read_verified_member_bytes(manifest_member)
        if hashlib.sha256(release_bytes).hexdigest() != release_manifest_sha:
            raise ExistingDatasetUpgradeError("pre-upgrade backup release manifest digest mismatch")
        release, expected = self._parse_program_inventory(release_bytes)
        actual = {
            key: value
            for key, value in self._entries.items()
            if key.startswith("program/") and value is not None and key != manifest_member
        }
        archived_pg = {
            key[len("program/"):]: value
            for key, value in actual.items()
            if key.startswith("program/postgresql/")
        }
        if (
            release.get("release_id") != release_id
            or release.get("max_schema_revision") != self._source_revision
            or not _is_nonempty_str(release.get("min_semantic_revision"))
            or actual != expected
            or not archived_pg
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade backup program inventory disagrees with archive")
        if self._app_dir is None:
            raise ExistingDatasetUpgradeError(
                "app_dir is required to verify pre-upgrade backup PostgreSQL program tree"
            )
        self._require_matching_local_postgres_program(archived_pg, self._app_dir)

    @staticmethod
    def _require_matching_local_postgres_program(
        archived_pg: dict[str, object],
        app_dir: Path,
    ) -> None:
        pg_root = app_dir / "postgresql"
        _reject_reparse_path(pg_root)
        if not pg_root.is_dir():
            raise ExistingDatasetUpgradeError("local PostgreSQL program tree is missing")
        current_pg: dict[str, dict[str, object]] = {}
        for path in pg_root.rglob("*"):
            _reject_reparse_path(path)
            if path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                current_pg[path.relative_to(app_dir).as_posix()] = {
                    "size": path.stat().st_size,
                    "sha256": digest,
                }
        if current_pg != archived_pg:
            raise ExistingDatasetUpgradeError(
                "pre-upgrade backup PostgreSQL program tree does not match the local installation"
            )

    def _is_matching_committed_operation(self, record: object) -> bool:
        return (
            isinstance(record, dict)
            and record.get("schema") == "ticketbox-lifecycle-operation-v2"
            and record.get("phase") == "committed"
            and record.get("install_id") == self._installation_id
            and record.get("dataset_id") == self._dataset_id
        )

    def _load_committed_history(self) -> list[dict[str, object]]:
        history_names = sorted(
            name
            for name in self._entries
            if name.startswith("machine/operations/history/") and name.endswith(".json")
        )
        committed: list[dict[str, object]] = []
        for name in history_names:
            record = json.loads(self._read_verified_member_bytes(name).decode("utf-8"))
            if self._is_matching_committed_operation(record):
                committed.append(record)
        return committed

    def _validate_upgrade_provenance(
        self,
        committed: list[dict[str, object]],
        origin: dict[str, object],
        identity: dict[str, object],
    ) -> None:
        upgrades = [
            rec
            for rec in committed
            if rec.get("kind") == "upgrade" and rec.get("expected_restore_epoch") == self._expected_restore_epoch
        ]
        targets = [
            rec
            for rec in upgrades
            if rec.get("release_manifest_sha256") == identity["release_manifest_sha256"]
            and rec.get("target_release_id") == identity["release_id"]
        ]
        if len(targets) != 1 or not _upgrade_chain_reaches_origin(origin, targets[0], upgrades):
            raise ExistingDatasetUpgradeError("pre-upgrade backup lacks committed upgrade provenance")

    def _validate_recovery_history(self, identity: dict[str, object]) -> None:
        committed = self._load_committed_history()
        origins = [rec for rec in committed if rec.get("kind") in {"install", "restore"}]
        if len(origins) != 1 or not _is_nonempty_str(origins[0].get("operation_id")):
            raise ExistingDatasetUpgradeError("pre-upgrade backup lacks committed owner recovery history")
        origin = origins[0]
        if origin.get("release_manifest_sha256") == identity["release_manifest_sha256"]:
            return
        self._validate_upgrade_provenance(committed, origin, identity)

    def _member_digest(self, relative: str) -> tuple[int, str]:
        cached = self._verified_members.get(relative)
        if cached is not None:
            return cached
        assert self._zip is not None
        try:
            with self._zip.open(relative, "r") as member:
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: member.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
        except (OSError, KeyError, zipfile.BadZipFile, zlib.error) as exc:
            raise ExistingDatasetUpgradeError(
                f"pre-upgrade backup archive member is missing or corrupt: {relative}"
            ) from exc
        result = (size, digest.hexdigest())
        self._verified_members[relative] = result
        return result

    def verify_file(
        self,
        path: Path,
        *,
        data_root: Path,
        expected_sha256: str | None = None,
    ) -> None:
        try:
            relative = "data/" + path.resolve().relative_to(data_root.resolve()).as_posix()
        except ValueError as exc:
            raise ExistingDatasetUpgradeError("retained original escaped data_root") from exc
        record = self._entries.get(relative)
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or _SHA256_HEX.fullmatch(record["sha256"]) is None
            or type(record.get("size")) is not int
            or record["size"] < 0
        ):
            raise ExistingDatasetUpgradeError("pre-upgrade cold backup is missing a retained original")
        disk_size = path.stat().st_size
        disk_digest = expected_sha256 or _file_sha256(path)
        if record["sha256"] != disk_digest or record["size"] != disk_size:
            raise ExistingDatasetUpgradeError("pre-upgrade cold backup index disagrees with disk")
        member_size, member_digest = self._member_digest(relative)
        if member_digest != disk_digest or member_size != disk_size:
            raise ExistingDatasetUpgradeError("pre-upgrade cold backup member bytes disagree with disk")


def _verify_snapshot_original(
    *,
    relative_path: str,
    tenant_id: str,
    expected_sha256: str | None,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.errors import AppError
    from app.services.original_read_service import read_original_snapshot_in_root
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    try:
        with read_original_snapshot_in_root(
            relative_path=relative_path,
            tenant_id=tenant_id,
            expected_sha256=expected_sha256,
            upload_root=upload_root,
        ) as snapshot:
            resolved = resolve_upload_path_for_tenant_in_root(
                relative_path,
                tenant_id,
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("retained original is missing on disk")
            archive.verify_file(resolved, data_root=data_root, expected_sha256=snapshot.sha256)
    except AppError as exc:
        raise ExistingDatasetUpgradeError(
            f"retained original verification failed: {exc.error}"
        ) from exc


def _verify_expense_primary_originals(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    select_hash = "image_hash" if "image_hash" in columns else "NULL AS image_hash"
    where_deleted = " AND image_deleted_at IS NULL" if "image_deleted_at" in columns else ""
    rows = connection.execute(
        text(
            f"SELECT tenant_id, image_path, {select_hash} "
            f"FROM public.expenses WHERE image_path IS NOT NULL{where_deleted}"
        )
    ).all()
    for tenant_id, image_path, image_hash in rows:
        _verify_snapshot_original(
            relative_path=str(image_path),
            tenant_id=str(tenant_id),
            expected_sha256=None if image_hash is None else str(image_hash),
            data_root=data_root,
            upload_root=upload_root,
            archive=archive,
        )


def _verify_expense_thumbnails(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    if "thumbnail_path" not in columns:
        return
    where_thumb = " AND thumbnail_deleted_at IS NULL" if "thumbnail_deleted_at" in columns else ""
    rows = connection.execute(
        text(
            f"SELECT tenant_id, thumbnail_path FROM public.expenses "
            f"WHERE thumbnail_path IS NOT NULL{where_thumb}"
        )
    ).all()
    for tenant_id, thumb_path in rows:
        resolved = resolve_upload_path_for_tenant_in_root(
            str(thumb_path),
            str(tenant_id),
            upload_root=upload_root,
        )
        if resolved is None or not resolved.is_file():
            raise ExistingDatasetUpgradeError("retained thumbnail is missing on disk")
        archive.verify_file(resolved, data_root=data_root)


def _verify_expense_pending_cleanups(
    connection: Connection,
    columns: set[str],
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.attachment_cleanup_contract import pending_cleanup_references
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    if "attachment_cleanup_request" not in columns:
        return
    rows = connection.execute(
        text(
            "SELECT tenant_id, attachment_cleanup_request FROM public.expenses "
            "WHERE attachment_cleanup_request IS NOT NULL"
        )
    ).all()
    for tenant_id, cleanup_req in rows:
        for reference in pending_cleanup_references(cleanup_req):
            resolved = resolve_upload_path_for_tenant_in_root(
                reference,
                str(tenant_id),
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("pending cleanup original reference is missing")
            archive.verify_file(resolved, data_root=data_root)


def _verify_expense_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    inspector = sa_inspect(connection)
    if not inspector.has_table("expenses", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("expenses", schema="public")}
    if "image_path" not in columns or "tenant_id" not in columns:
        return
    _verify_expense_primary_originals(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )
    _verify_expense_thumbnails(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )
    _verify_expense_pending_cleanups(
        connection, columns, data_root=data_root, upload_root=upload_root, archive=archive
    )


def _expenses_projection_cte(inspector) -> str:
    if not inspector.has_table("expenses", schema="public"):
        return (
            "SELECT CAST(NULL AS TEXT) AS tenant_id, CAST(NULL AS INTEGER) AS id, "
            "CAST(NULL AS TEXT) AS public_id, CAST(NULL AS TEXT) AS image_path, "
            "CAST(NULL AS TEXT) AS image_hash, CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at, "
            "CAST(NULL AS JSONB) AS attachment_cleanup_request WHERE FALSE"
        )
    columns = {col["name"] for col in inspector.get_columns("expenses", schema="public")}
    if not {"id", "tenant_id", "public_id", "image_path"}.issubset(columns):
        return (
            "SELECT CAST(NULL AS TEXT) AS tenant_id, CAST(NULL AS INTEGER) AS id, "
            "CAST(NULL AS TEXT) AS public_id, CAST(NULL AS TEXT) AS image_path, "
            "CAST(NULL AS TEXT) AS image_hash, CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at, "
            "CAST(NULL AS JSONB) AS attachment_cleanup_request WHERE FALSE"
        )
    hash_expr = "image_hash" if "image_hash" in columns else "CAST(NULL AS TEXT) AS image_hash"
    deleted_expr = (
        "image_deleted_at"
        if "image_deleted_at" in columns
        else "CAST(NULL AS TIMESTAMPTZ) AS image_deleted_at"
    )
    cleanup_expr = (
        "attachment_cleanup_request"
        if "attachment_cleanup_request" in columns
        else "CAST(NULL AS JSONB) AS attachment_cleanup_request"
    )
    return (
        f"SELECT tenant_id, id, public_id, image_path, {hash_expr}, {deleted_expr}, {cleanup_expr} "
        "FROM public.expenses"
    )


def _verify_historical_receipt_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.services.original_reference_queries import historical_original_is_cleaned

    inspector = sa_inspect(connection)
    if not inspector.has_table("api_idempotency_keys", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("api_idempotency_keys", schema="public")}
    if not {"id", "tenant_id", "status", "resource_type", "response_body"}.issubset(columns):
        return
    expenses_cte = _expenses_projection_cte(inspector)
    query = text(
        "WITH accepted AS ("
        " SELECT r.id, r.tenant_id, r.resource_type,"
        "  CASE WHEN r.resource_type = 'expense_offset' THEN r.response_body -> 'root'"
        "       ELSE r.response_body END AS body"
        " FROM public.api_idempotency_keys AS r"
        " WHERE r.status = 'succeeded'"
        "   AND r.resource_type IN ('expense', 'expense_offset', 'upload_receipt')"
        "   AND r.response_body IS NOT NULL"
        "),"
        " classified AS ("
        " SELECT a.id AS accepted_id, a.tenant_id, a.resource_type, a.body,"
        "  (a.resource_type = 'expense'"
        "   AND (a.body ->> 'operation') = ANY(:ops)"
        "   AND (a.body ->> 'sha256') IS NOT NULL) AS original_command"
        " FROM accepted AS a"
        "),"
        " projected AS ("
        " SELECT c.accepted_id, c.tenant_id, c.resource_type, c.body, c.original_command,"
        "  CAST(CASE WHEN c.original_command THEN c.body ->> 'expense_id'"
        "            ELSE c.body ->> 'id' END AS INTEGER) AS expense_id,"
        "  (c.body ->> 'public_id') AS expense_public_id,"
        "  CASE WHEN c.original_command THEN c.body ->> 'sha256'"
        "       ELSE c.body ->> 'image_hash' END AS image_hash,"
        "  (c.body ->> 'image_deleted_at') AS image_deleted_at"
        " FROM classified AS c"
        "),"
        f" exp AS ({expenses_cte}),"
        " resolved AS ("
        " SELECT p.accepted_id, p.tenant_id, p.expense_id, p.expense_public_id,"
        "  CASE WHEN (p.resource_type = 'upload_receipt' OR p.original_command)"
        "        AND p.image_hash = e.image_hash THEN e.image_path"
        "       WHEN (p.resource_type = 'upload_receipt' OR p.original_command) THEN NULL"
        "       ELSE p.body ->> 'image_path' END AS image_path,"
        "  p.image_hash, p.image_deleted_at,"
        "  e.image_path AS current_image_path,"
        "  e.image_deleted_at AS current_image_deleted_at,"
        "  e.attachment_cleanup_request"
        " FROM projected AS p"
        " LEFT OUTER JOIN exp AS e"
        "   ON e.tenant_id = p.tenant_id"
        "  AND e.id = p.expense_id"
        "  AND e.public_id = p.expense_public_id"
        " WHERE p.expense_id IS NOT NULL"
        ")"
        " SELECT r.tenant_id, r.expense_id, r.expense_public_id, r.image_path, r.image_hash,"
        "  r.image_deleted_at,"
        "  MAX(CASE WHEN r.image_deleted_at IS NOT NULL THEN 1 ELSE 0 END) OVER ("
        "    PARTITION BY r.tenant_id, r.expense_id, r.expense_public_id, r.image_path"
        "  ) AS historical_image_cleaned,"
        "  r.current_image_path, r.current_image_deleted_at, r.attachment_cleanup_request"
        " FROM resolved AS r"
        " ORDER BY r.accepted_id"
    )
    try:
        rows = connection.execute(query, {"ops": sorted(_ORIGINAL_RECEIPT_OPERATIONS)}).mappings().all()
    except SQLAlchemyError as exc:
        raise ExistingDatasetUpgradeError("historical original receipt projection failed") from exc
    for row in rows:
        if historical_original_is_cleaned(row):
            continue
        image_path = row["image_path"]
        if not isinstance(image_path, str) or not image_path:
            continue
        image_hash = row["image_hash"]
        _verify_snapshot_original(
            relative_path=image_path,
            tenant_id=str(row["tenant_id"]),
            expected_sha256=image_hash if isinstance(image_hash, str) and image_hash else None,
            data_root=data_root,
            upload_root=upload_root,
            archive=archive,
        )


def _verify_debt_bill_originals(
    connection: Connection,
    *,
    data_root: Path,
    upload_root: Path,
    archive: _VerifiedBackupArchive,
) -> None:
    from app.attachment_cleanup_contract import pending_cleanup_references
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    inspector = sa_inspect(connection)
    if not inspector.has_table("debt_bill_captures", schema="public"):
        return
    columns = {col["name"] for col in inspector.get_columns("debt_bill_captures", schema="public")}
    if "image_path" not in columns or "tenant_id" not in columns:
        return
    deleted_expr = "image_deleted_at" if "image_deleted_at" in columns else "NULL AS image_deleted_at"
    cleanup_expr = (
        "attachment_cleanup_request"
        if "attachment_cleanup_request" in columns
        else "NULL AS attachment_cleanup_request"
    )
    hash_expr = "image_hash" if "image_hash" in columns else "NULL AS image_hash"
    rows = connection.execute(
        text(
            f"SELECT tenant_id, image_path, {deleted_expr}, {cleanup_expr}, {hash_expr} "
            "FROM public.debt_bill_captures"
        )
    ).all()
    for tenant_id, image_path, deleted_at, cleanup_req, image_hash in rows:
        if deleted_at is None and image_path:
            _verify_snapshot_original(
                relative_path=str(image_path),
                tenant_id=str(tenant_id),
                expected_sha256=None if image_hash is None else str(image_hash),
                data_root=data_root,
                upload_root=upload_root,
                archive=archive,
            )
        for reference in pending_cleanup_references(cleanup_req):
            resolved = resolve_upload_path_for_tenant_in_root(
                reference,
                str(tenant_id),
                upload_root=upload_root,
            )
            if resolved is None or not resolved.is_file():
                raise ExistingDatasetUpgradeError("retained debt bill original is missing")
            archive.verify_file(resolved, data_root=data_root)


def _verify_upgrade_originals(
    connection: Connection,
    *,
    data_root: Path,
    backup_archive: Path,
    backup_archive_sha256: str,
    dataset_id: str,
    installation_id: str,
    expected_restore_epoch: int,
    source_revision: str,
    app_dir: Path | None = None,
) -> None:
    if not data_root.is_absolute() or not data_root.is_dir():
        raise ExistingDatasetUpgradeError("upgrade data_root is invalid or missing")
    upload_root = (data_root / "app" / "uploads").resolve()
    with _VerifiedBackupArchive(
        backup_archive,
        backup_archive_sha256,
        dataset_id=dataset_id,
        installation_id=installation_id,
        expected_restore_epoch=expected_restore_epoch,
        source_revision=source_revision,
        app_dir=app_dir,
    ) as archive:
        _verify_expense_originals(connection, data_root=data_root, upload_root=upload_root, archive=archive)
        _verify_historical_receipt_originals(
            connection, data_root=data_root, upload_root=upload_root, archive=archive
        )
        _verify_debt_bill_originals(connection, data_root=data_root, upload_root=upload_root, archive=archive)


def _require_absolute_path(value: object, *, message: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ExistingDatasetUpgradeError(message)
    return value


def run_existing_dataset_upgrade_action(
    *,
    database_url: str,
    pgpassfile: Path,
    source_revision: str,
    target_revision: str,
    dataset_id: str,
    installation_id: str,
    expected_restore_epoch: int,
    operation_id: str,
    data_root: Path | None = None,
    backup_archive: Path | None = None,
    backup_archive_sha256: str | None = None,
    app_dir: Path | None = None,
    program: DatabaseGenerationProgram | None = None,
    contract: ManagedPostgresRuntimeContractV1 | None = None,
    seal_runtime_authority: bool = True,
    machine_secret: bool = True,
) -> dict[str, object]:
    bound_dataset_id = _canonical_uuid(dataset_id, label="dataset_id")
    bound_installation_id = _canonical_uuid(installation_id, label="installation_id")
    if not _is_nonnegative_int(expected_restore_epoch):
        raise ExistingDatasetUpgradeError("expected_restore_epoch is invalid")
    source = _require_revision(source_revision, label="source_revision")
    target = _require_revision(target_revision, label="target_revision")
    try:
        bound_operation_id = validate_generation_operation_id(operation_id)
    except DatabaseGenerationExecutionError as exc:
        raise ExistingDatasetUpgradeError(str(exc)) from exc
    bound_pgpass = _require_absolute_path(pgpassfile, message="pgpass path must be absolute")
    bound_data_root = _require_absolute_path(data_root, message="data_root must be an absolute path")
    bound_backup_archive = _require_absolute_path(backup_archive, message="backup_archive must be an absolute path")
    bound_app_dir = (
        _require_absolute_path(app_dir, message="app_dir must be an absolute path")
        if app_dir is not None
        else None
    )
    bound_backup_sha = _require_sha256(backup_archive_sha256, label="backup_archive_sha256")
    resolved_program = _resolve_program(program)
    if target != resolved_program.target_revision:
        raise ExistingDatasetUpgradeError("target_revision differs from the packaged generation program")
    effective_contract = contract or ManagedPostgresRuntimeContractV1(
        database_name=DATABASE_NAME,
        migrator_role=MIGRATOR_ROLE,
        schema_owner_role=SCHEMA_OWNER_ROLE,
        lease_label=MIGRATION_LEASE_LABEL,
        transaction_timeout_ms=_TRANSACTION_TIMEOUT_MS,
    )
    try:
        outcome = ManagedPostgresMigrationRuntimeV1(effective_contract).run(
            database_url=database_url,
            pgpassfile=bound_pgpass,
            program=resolved_program,
            source_revision=source,
            target_revision=target,
            generation_operation_id=bound_operation_id,
            expected_dataset_id=bound_dataset_id,
            expected_restore_epoch=expected_restore_epoch,
            expected_installation_id=bound_installation_id,
            seal_runtime_authority=seal_runtime_authority,
            machine_secret=machine_secret,
            backup_archive_sha256=bound_backup_sha,
            pre_migration_check=lambda connection: _verify_upgrade_originals(
                connection,
                data_root=bound_data_root,
                backup_archive=bound_backup_archive,
                backup_archive_sha256=bound_backup_sha,
                dataset_id=bound_dataset_id,
                installation_id=bound_installation_id,
                expected_restore_epoch=expected_restore_epoch,
                source_revision=source,
                app_dir=bound_app_dir,
            ),
        )
    except ManagedPostgresMigrationRuntimeError as exc:
        raise ExistingDatasetUpgradeError(str(exc)) from exc
    return {
        "schema": RESULT_SCHEMA,
        "operation_id": bound_operation_id,
        "dataset_id": bound_dataset_id,
        "installation_id": bound_installation_id,
        "restore_epoch": expected_restore_epoch,
        "source_revision": source,
        "target_revision": target,
        "alembic_revision": target,
        "backup_archive_sha256": bound_backup_sha,
        "result": outcome,
    }


__all__ = [
    "ExistingDatasetUpgradeError",
    "RESULT_SCHEMA",
    "run_existing_dataset_upgrade_action",
]
