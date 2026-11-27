"""Stateless safety, manifest, and provenance rules for pre-upgrade cold backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
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


class ExistingDatasetUpgradeError(RuntimeError):
    """The offline existing-dataset upgrade could not be proven safe."""


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_hex_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


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


def _is_valid_inventory_item(item: object) -> bool:
    return (
        isinstance(item, dict)
        and _is_nonempty_str(item.get("path"))
        and _is_nonnegative_int(item.get("size"))
        and _is_hex_sha256(item.get("sha256"))
    )


def _parse_program_inventory(
    release_bytes: bytes,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    try:
        release = json.loads(release_bytes.decode("utf-8"))
        inventory = release["immutable_payload"]["files"]
        if not isinstance(inventory, list) or not inventory:
            raise ValueError("empty inventory")
        expected: dict[str, dict[str, object]] = {}
        for item in inventory:
            if not _is_valid_inventory_item(item):
                raise ValueError("invalid inventory entry")
            key = "program/" + item["path"]
            if key in expected:
                raise ValueError("duplicate inventory entry")
            expected[key] = {"size": item["size"], "sha256": item["sha256"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise ExistingDatasetUpgradeError("pre-upgrade backup program inventory is incomplete") from exc
    return release, expected


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
