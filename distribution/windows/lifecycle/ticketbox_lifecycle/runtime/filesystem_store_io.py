"""Validation, deserialization, connector probing, and atomic JSON I/O for filesystem stores."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import fields
from pathlib import Path
from typing import cast

from ticketbox_lifecycle.connector_schema import ConnectorOperation, parse_operation, parse_state
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME as CONNECTOR_SERVICE_NAME
from ticketbox_lifecycle.runtime.windows_security_native import reject_reparse_components
from ticketbox_lifecycle.runtime.windows_services import service_registered
from ticketbox_lifecycle.schemas import (
    APPLY_SEQUENCE,
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    REINSTALL_SEQUENCE,
    UNINSTALL_SEQUENCE,
    UPGRADE_SEQUENCE,
    ActiveOperation,
    ApplyStepName,
    DurablePhase,
    InstallationBinding,
    ReinstallOperation,
    RestoreOperation,
    UninstallOperation,
    UninstallStepName,
    UpgradeOperation,
    UpgradeStepName,
)

_ACTIVE_OPERATION_FIELDS = frozenset(field.name for field in fields(ActiveOperation))
_UPGRADE_EXTRA_FIELDS = frozenset({
    "expected_restore_epoch",
    "previous_release_id",
    "previous_release_manifest_sha256",
    "source_schema_revision",
    "backup_path",
    "backup_sha256",
    "business_writes_opened",
})
_INSTALLATION_BINDING_FIELDS = frozenset(field.name for field in fields(InstallationBinding))
_RELEASE_ID_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")

_OPERATION_CLASS_BY_KIND = {
    "install": ActiveOperation,
    "restore": RestoreOperation,
    "upgrade": UpgradeOperation,
    "reinstall": ReinstallOperation,
    "uninstall": UninstallOperation,
}


def _expected_operation_fields(kind: str) -> frozenset[str]:
    if kind in {"restore", "reinstall", "uninstall"}:
        return _ACTIVE_OPERATION_FIELDS | {"expected_restore_epoch"}
    if kind == "upgrade":
        return _ACTIVE_OPERATION_FIELDS | _UPGRADE_EXTRA_FIELDS
    return _ACTIVE_OPERATION_FIELDS


def _operation_type(payload: dict[str, object]):
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in _OPERATION_CLASS_BY_KIND:
        raise LifecycleError("bad_operation_kind", "operation kind is unsupported")
    if set(payload) != _expected_operation_fields(kind):
        raise LifecycleError("bad_operation_fields", "operation fields are not closed")
    if payload.get("schema") != OPERATION_SCHEMA:
        raise LifecycleError("bad_operation_schema", "operation schema is not v2")
    if kind == "restore":
        epoch = payload["expected_restore_epoch"]
        if type(epoch) is not int or epoch <= 0:
            raise LifecycleError("bad_restore_epoch", "restore operation requires a positive target epoch")
    elif kind in {"reinstall", "uninstall"}:
        epoch = payload["expected_restore_epoch"]
        if type(epoch) is not int or epoch < 0:
            raise LifecycleError("bad_operation_epoch", f"{kind} operation requires a non-negative restore epoch")
    elif kind == "upgrade":
        _validate_upgrade_payload(payload)
    return _OPERATION_CLASS_BY_KIND[kind], kind


def _validate_upgrade_previous_lineage(payload: dict[str, object]) -> None:
    previous = payload["previous_release_id"]
    if (
        not isinstance(previous, str)
        or _RELEASE_ID_PATTERN.fullmatch(previous) is None
        or previous == payload["target_release_id"]
    ):
        raise LifecycleError("bad_upgrade_previous_release", "upgrade previous_release_id is invalid")
    prev_manifest = payload["previous_release_manifest_sha256"]
    if (
        not isinstance(prev_manifest, str)
        or re.fullmatch(r"[0-9a-f]{64}", prev_manifest) is None
        or prev_manifest == payload["release_manifest_sha256"]
    ):
        raise LifecycleError(
            "bad_upgrade_previous_manifest",
            "upgrade previous_release_manifest_sha256 is invalid",
        )


def _validate_upgrade_payload(payload: dict[str, object]) -> None:
    epoch = payload["expected_restore_epoch"]
    if type(epoch) is not int or epoch < 0:
        raise LifecycleError("bad_upgrade_epoch", "upgrade operation requires a non-negative restore epoch")
    _validate_upgrade_previous_lineage(payload)
    source_rev = payload["source_schema_revision"]
    if not isinstance(source_rev, str) or not source_rev:
        raise LifecycleError("bad_upgrade_source_revision", "upgrade source_schema_revision is invalid")
    backup_path = payload["backup_path"]
    backup_sha = payload["backup_sha256"]
    if not isinstance(backup_path, str) or not isinstance(backup_sha, str):
        raise LifecycleError("bad_upgrade_backup", "upgrade backup metadata is invalid")
    if backup_sha and re.fullmatch(r"[0-9a-f]{64}", backup_sha) is None:
        raise LifecycleError("bad_upgrade_backup", "upgrade backup sha256 is invalid")
    if type(payload["business_writes_opened"]) is not bool:
        raise LifecycleError("bad_upgrade_writes_flag", "upgrade business_writes_opened must be a boolean")


def operation_from_payload(payload: dict[str, object]) -> ActiveOperation | ConnectorOperation:
    if payload.get("schema") == "ticketbox-lifecycle-operation-v3":
        return parse_operation(payload)
    operation_type, kind = _operation_type(payload)
    completed_step = payload.get("completed_step")
    valid_steps = {
        "upgrade": UPGRADE_SEQUENCE,
        "reinstall": REINSTALL_SEQUENCE,
        "uninstall": UNINSTALL_SEQUENCE,
    }.get(kind, APPLY_SEQUENCE)
    if completed_step is not None and completed_step not in valid_steps:
        raise LifecycleError("bad_operation_progress", "operation completed_step is invalid")
    health_attestation_key = str(payload.get("health_attestation_key") or "")
    if re.fullmatch(r"[0-9a-f]{64}", health_attestation_key) is None:
        raise LifecycleError("bad_operation_attestation", "operation health attestation key is invalid")
    extra: dict[str, object] = {}
    if kind in {"restore", "reinstall", "uninstall"}:
        extra["expected_restore_epoch"] = payload["expected_restore_epoch"]
    elif kind == "upgrade":
        extra = {
            "expected_restore_epoch": payload["expected_restore_epoch"],
            "previous_release_id": str(payload["previous_release_id"]),
            "previous_release_manifest_sha256": str(payload["previous_release_manifest_sha256"]),
            "source_schema_revision": str(payload["source_schema_revision"]),
            "backup_path": str(payload["backup_path"]),
            "backup_sha256": str(payload["backup_sha256"]),
            "business_writes_opened": bool(payload["business_writes_opened"]),
        }
    return operation_type(
        schema=OPERATION_SCHEMA,
        operation_id=str(payload["operation_id"]),
        kind=payload["kind"],
        request_hash=str(payload["request_hash"]),
        target_release_id=str(payload["target_release_id"]),
        data_root=str(payload["data_root"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
        backend_port=int(payload["backend_port"]),
        phase=cast(DurablePhase, payload["phase"]),
        no_return_point=bool(payload["no_return_point"]),
        completed_step=cast(ApplyStepName | UpgradeStepName | UninstallStepName | None, completed_step),
        install_id=str(payload.get("install_id") or ""),
        dataset_id=str(payload.get("dataset_id") or ""),
        schema_revision=str(payload.get("schema_revision") or ""),
        health_attestation_key=health_attestation_key,
        **extra,
    )


def binding_from_payload(payload: dict[str, object]) -> InstallationBinding:
    if payload.get("schema") != INSTALLATION_SCHEMA:
        raise LifecycleError("bad_binding_schema", "installation.json schema is not v1")
    if set(payload) != _INSTALLATION_BINDING_FIELDS:
        raise LifecycleError("bad_binding_fields", "installation.json fields are not closed")
    health_attestation_key = str(payload["health_attestation_key"])
    if re.fullmatch(r"[0-9a-f]{64}", health_attestation_key) is None:
        raise LifecycleError(
            "bad_binding_attestation",
            "installation.json health attestation key is invalid",
        )
    active_release_id = str(payload["active_release_id"])
    previous_release_id = payload.get("previous_release_id")
    if previous_release_id is not None and (
        not isinstance(previous_release_id, str)
        or _RELEASE_ID_PATTERN.fullmatch(previous_release_id) is None
        or previous_release_id == active_release_id
    ):
        raise LifecycleError(
            "bad_binding_previous_release",
            "installation.json previous_release_id is invalid",
        )
    return InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=str(payload["install_id"]),
        dataset_id=str(payload["dataset_id"]),
        expected_restore_epoch=int(payload["expected_restore_epoch"]),
        data_root=str(payload["data_root"]),
        active_release_id=active_release_id,
        previous_release_id=previous_release_id,
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
        postgres_major=int(payload["postgres_major"]),
        pg_service_name=str(payload["pg_service_name"]),
        backend_service_name=str(payload["backend_service_name"]),
        pg_port=int(payload["pg_port"]),
        backend_port=int(payload["backend_port"]),
        health_attestation_key=health_attestation_key,
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError(
                "machine_state_invalid",
                f"duplicate JSON key in machine state: {key}",
            )
        result[key] = value
    return result


def _connector_state_file_present(
    state_path: Path,
    *,
    binding: InstallationBinding | None,
    allowed_manifest_shas: frozenset[str],
    verify_state_file: Callable[[Path], None] | None,
    reject_reparse: Callable[[Path], None] = reject_reparse_components,
) -> bool:
    try:
        reject_reparse(state_path)
        if not state_path.is_file():
            return True
        if verify_state_file is not None:
            verify_state_file(state_path)
        raw = state_path.read_bytes()
        if verify_state_file is not None:
            verify_state_file(state_path)
        if len(raw) > 8192:
            return True
        state = parse_state(
            json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
        )
    except (OSError, UnicodeError, ValueError, LifecycleError):
        return True
    if state.configured or state.enabled or state.tunnel_id is not None or binding is None:
        return True
    expected_shas = allowed_manifest_shas or frozenset({binding.release_manifest_sha256})
    return (
        state.install_id != binding.install_id
        or state.dataset_id != binding.dataset_id
        or state.expected_restore_epoch != binding.expected_restore_epoch
        or state.release_manifest_sha256 not in expected_shas
    )


def _managed_connector_present(
    machine_root: Path,
    *,
    binding: InstallationBinding | None = None,
    allowed_manifest_shas: frozenset[str] = frozenset(),
    verify_state_file: Callable[[Path], None] | None = None,
    is_service_registered: Callable[[str], bool] = service_registered,
    reject_reparse: Callable[[Path], None] = reject_reparse_components,
) -> bool:
    if is_service_registered(CONNECTOR_SERVICE_NAME):
        return True
    connectors_root = machine_root / "connectors"
    connector_dir = connectors_root / "cloudflare"
    try:
        reject_reparse(connectors_root)
        reject_reparse(connector_dir)
    except (OSError, LifecycleError):
        return True
    secrets_dir = connector_dir / "secrets"
    if os.path.lexists(secrets_dir):
        try:
            reject_reparse(secrets_dir)
            if not secrets_dir.is_dir() or any(secrets_dir.iterdir()):
                return True
        except (OSError, LifecycleError):
            return True
    state_path = connector_dir / "state.json"
    if os.path.lexists(state_path):
        return _connector_state_file_present(
            state_path,
            binding=binding,
            allowed_manifest_shas=allowed_manifest_shas,
            verify_state_file=verify_state_file,
            reject_reparse=reject_reparse,
        )
    return False


def _write_temp_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        _write_json_fd(fd, payload)
        return Path(tmp_name)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _write_exact_temp_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        _write_json_fd(fd, payload)
        return path
    except BaseException:
        with suppress(OSError):
            os.close(fd)
        if os.path.exists(path):
            os.unlink(path)
        raise


def _write_json_fd(fd: int, payload: dict[str, object]) -> None:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
