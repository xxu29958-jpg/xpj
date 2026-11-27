"""Stateful pre-upgrade cold-backup archive verification context."""

from __future__ import annotations

import hashlib
import json
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO

from app.database._existing_dataset_upgrade_archive_rules import (
    _COLD_COPY_COMPONENTS,
    _COLD_COPY_CONNECTOR_POLICY,
    _COLD_COPY_REQUIRED_FILES,
    _COLD_COPY_SCHEMA,
    _SHA256_HEX,
    ExistingDatasetUpgradeError,
    _file_sha256,
    _infer_frozen_app_dir,
    _is_connector_secret_entry,
    _is_hex_sha256,
    _is_nonempty_str,
    _is_nonnegative_int,
    _is_positive_int,
    _parse_program_inventory,
    _require_matching_local_postgres_program,
    _require_safe_archive_members,
    _require_valid_recovery_point,
    _upgrade_chain_reaches_origin,
)


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

    def _validate_program_inventory(self, release_id: str, release_manifest_sha: str) -> None:
        manifest_member = f"program/releases/{release_id}/release-manifest.json"
        release_bytes = self._read_verified_member_bytes(manifest_member)
        if hashlib.sha256(release_bytes).hexdigest() != release_manifest_sha:
            raise ExistingDatasetUpgradeError("pre-upgrade backup release manifest digest mismatch")
        release, expected = _parse_program_inventory(release_bytes)
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
        _require_matching_local_postgres_program(archived_pg, self._app_dir)

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
