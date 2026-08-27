from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import replace
from pathlib import Path, PurePosixPath

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest

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
PG_SERVICE_NAME = "TicketboxPg"
BACKEND_SERVICE_NAME = "TicketboxBackend"
PG_PORT = 5432
BACKEND_PORT = 8000
POSTGRES_MAJOR = 17


class WindowsShipmentVerifier:
    def __init__(self, expected_app_dir: Path, expected_program_data_root: Path) -> None:
        self._expected_app_dir = expected_app_dir
        self._expected_program_data_root = expected_program_data_root

    def bind_and_verify(self, request: InstallRequest) -> InstallRequest:
        app_dir = Path(request.app_dir)
        if _absolute_path_key(app_dir) != _absolute_path_key(self._expected_app_dir):
            raise LifecycleViolation(
                "untrusted_install_root",
                "installed application root must be the exact Ticketbox Program Files directory",
            )
        _require_trusted_setup_contract(request, self._expected_program_data_root)
        manifest_path = (
            app_dir
            / "releases"
            / request.target_release_id
            / "release-manifest.json"
        )
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
        if (
            declared_manifest_sha in {"", "pending"}
            or declared_manifest_sha != actual_manifest_sha
        ):
            raise LifecycleViolation(
                "release_hash_mismatch",
                "installed release manifest does not match this Setup request",
            )
        if request.operation_id != f"fresh-{actual_manifest_sha}":
            raise LifecycleViolation(
                "untrusted_setup_request",
                "privileged request does not match the trusted Setup contract",
            )
        manifest = _parse_manifest(manifest_bytes, request)
        expected = _expected_files(manifest, app_dir, manifest_path)
        actual = _actual_files(app_dir, manifest_path)
        if set(expected) != set(actual):
            raise LifecycleViolation(
                "shipment_file_set_mismatch",
                "immutable shipment has missing or unexpected files",
            )
        for key, record in expected.items():
            path = actual[key]
            if path.stat().st_size != record["size"] or _sha256(path) != record["sha256"]:
                raise LifecycleViolation(
                    "shipment_file_mismatch",
                    f"immutable shipment file does not match: {record['path']}",
                )
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != actual_manifest_sha:
            raise LifecycleViolation(
                "release_manifest_changed",
                "release manifest changed during immutable shipment verification",
            )
        return replace(
            request,
            release_manifest_sha256=actual_manifest_sha,
            schema_revision=str(manifest["max_schema_revision"]),
            schema_min_compatible=str(manifest["product_version"]),
            semantic_revision=str(manifest["min_semantic_revision"]),
        )


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


def _parse_manifest(payload: bytes, request: InstallRequest) -> dict[str, object]:
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleViolation("release_manifest_invalid", "release manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise LifecycleViolation("release_manifest_invalid", "release manifest shape is not closed")
    if (
        manifest["schema"] != "ticketbox-release-manifest-v1"
        or manifest["release_id"] != request.target_release_id
        or not isinstance(manifest["product_version"], str)
        or _PRODUCT_VERSION.fullmatch(manifest["product_version"]) is None
        or manifest["product_version"] != request.target_release_id
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


def _actual_files(app_dir: Path, manifest_path: Path) -> dict[str, Path]:
    reject_reparse_components(app_dir)
    if not app_dir.is_dir():
        raise LifecycleViolation("shipment_missing", "immutable shipment root is absent")
    manifest_relative = manifest_path.relative_to(app_dir).as_posix().casefold()
    records: dict[str, Path] = {}
    for root, directories, files in os.walk(app_dir, topdown=True, followlinks=False):
        directories.sort(key=str.casefold)
        files.sort(key=str.casefold)
        root_path = Path(root)
        for name in directories:
            _require_regular_path(root_path / name, directory=True)
        for name in files:
            path = root_path / name
            _require_regular_path(path, directory=False)
            relative = path.relative_to(app_dir).as_posix()
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
