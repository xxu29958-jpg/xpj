"""Read non-secret connector authority for the authenticated loopback Manager."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.config import DATA_ROOT, RUNTIME_SETTINGS_PATH, runtime_settings_service_owned
from app.services import secure_file
from app.services.runtime_settings_store import read_runtime_settings
from app.windows_connector_authority import ConnectorAuthorityError, require_connector_binding, require_connector_state

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")
_BASE_OP_FIELDS = frozenset({
    "schema", "operation_id", "kind", "request_hash", "target_release_id",
    "data_root", "release_manifest_sha256", "backend_port", "phase",
    "no_return_point", "completed_step", "install_id", "dataset_id",
    "schema_revision", "health_attestation_key",
})
_RESTORE_OP_FIELDS = _BASE_OP_FIELDS | frozenset({"expected_restore_epoch"})
_UPGRADE_OP_FIELDS = _BASE_OP_FIELDS | frozenset({
    "expected_restore_epoch", "previous_release_id", "previous_release_manifest_sha256",
    "source_schema_revision", "backup_path", "backup_sha256", "business_writes_opened",
})
_MAX_UPGRADE_CHAIN_HOPS = 64


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _read_record(path: Path) -> dict | None:
    if not os.path.lexists(path):
        return None
    advapi, kernel = secure_file._windows_apis()
    service_sid = secure_file._current_process_service_sid(advapi, kernel)
    with secure_file._hold_windows_protected_file(path,
        owner_sids=frozenset({"S-1-5-18", "S-1-5-32-544"}),
        access_rules={"S-1-5-18": 0x1F01FF, "S-1-5-32-544": 0x1F01FF, service_sid: 0x120089}) as protected, protected.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ConnectorAuthorityError("connector record exceeds its limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ConnectorAuthorityError("connector record must be an object")
    return value


def _valid_common_committed(
    record: dict,
    *,
    expected_op_id: str,
    expected_kind: str,
    expected_manifest: str,
    expected_release: str | None,
    binding: dict,
) -> bool:
    target = record.get("target_release_id")
    port = record.get("backend_port")
    return (
        record.get("schema") == "ticketbox-lifecycle-operation-v2"
        and record.get("kind") == expected_kind
        and record.get("operation_id") == expected_op_id
        and record.get("phase") == "committed"
        and record.get("no_return_point") is True
        and record.get("completed_step") == "health"
        and record.get("release_manifest_sha256") == expected_manifest
        and record.get("install_id") == binding.get("install_id")
        and record.get("dataset_id") == binding.get("dataset_id")
        and isinstance(target, str)
        and _RELEASE_ID.fullmatch(target) is not None
        and (expected_release is None or target == expected_release)
        and _is_hex64(record.get("request_hash"))
        and _is_hex64(record.get("health_attestation_key"))
        and isinstance(record.get("data_root"), str)
        and bool(record["data_root"])
        and isinstance(record.get("schema_revision"), str)
        and bool(record["schema_revision"])
        and type(port) is int
        and 1 <= port <= 65535
    )


def _valid_committed_upgrade(
    record: object,
    *,
    expected_manifest: str,
    expected_release: str | None,
    binding: dict,
) -> bool:
    if not isinstance(record, dict) or set(record) != _UPGRADE_OP_FIELDS:
        return False
    if not _valid_common_committed(
        record,
        expected_op_id=f"upgrade-{expected_manifest}",
        expected_kind="upgrade",
        expected_manifest=expected_manifest,
        expected_release=expected_release,
        binding=binding,
    ):
        return False
    prev_release = record["previous_release_id"]
    prev_manifest = record["previous_release_manifest_sha256"]
    binding_epoch = binding.get("expected_restore_epoch")
    record_epoch = record["expected_restore_epoch"]
    return (
        type(binding_epoch) is int
        and type(record_epoch) is int
        and record_epoch == binding_epoch
        and isinstance(prev_release, str)
        and _RELEASE_ID.fullmatch(prev_release) is not None
        and prev_release != record["target_release_id"]
        and _is_hex64(prev_manifest)
        and prev_manifest != expected_manifest
        and isinstance(record["source_schema_revision"], str)
        and bool(record["source_schema_revision"])
        and isinstance(record["backup_path"], str)
        and bool(record["backup_path"])
        and _is_hex64(record["backup_sha256"])
        and record["business_writes_opened"] is True
    )


def _valid_committed_origin(
    history_dir: Path,
    *,
    manifest: str,
    expected_release: str,
    binding: dict,
) -> bool:
    epoch = binding.get("expected_restore_epoch")
    if type(epoch) is int and epoch == 0:
        op_id = f"fresh-{manifest}"
        record = _read_record(history_dir / f"{op_id}.json")
        return (
            isinstance(record, dict)
            and set(record) == _BASE_OP_FIELDS
            and _valid_common_committed(
                record,
                expected_op_id=op_id,
                expected_kind="install",
                expected_manifest=manifest,
                expected_release=expected_release,
                binding=binding,
            )
        )
    if type(epoch) is int and epoch > 0:
        op_id = f"restore-{manifest}"
        record = _read_record(history_dir / f"{op_id}.json")
        return (
            isinstance(record, dict)
            and set(record) == _RESTORE_OP_FIELDS
            and type(record["expected_restore_epoch"]) is int
            and record["expected_restore_epoch"] == epoch
            and _valid_common_committed(
                record,
                expected_op_id=op_id,
                expected_kind="restore",
                expected_manifest=manifest,
                expected_release=expected_release,
                binding=binding,
            )
        )
    return False


def _upgrade_chain_connects_manifests(machine: Path, binding: dict, *, prior_manifest: str) -> bool:
    history_dir = machine / "operations" / "history"
    current_manifest = binding.get("release_manifest_sha256")
    if not _is_hex64(current_manifest) or not _is_hex64(prior_manifest):
        return False
    assert isinstance(current_manifest, str)
    cursor_manifest = current_manifest
    expected_release: str | None = None
    visited: set[str] = set()
    seen_prior = False
    for _ in range(_MAX_UPGRADE_CHAIN_HOPS):
        if cursor_manifest in visited:
            return False
        visited.add(cursor_manifest)
        record = _read_record(history_dir / f"upgrade-{cursor_manifest}.json")
        if record is None:
            if not seen_prior or expected_release is None:
                return False
            return _valid_committed_origin(
                history_dir,
                manifest=cursor_manifest,
                expected_release=expected_release,
                binding=binding,
            )
        if not _valid_committed_upgrade(
            record,
            expected_manifest=cursor_manifest,
            expected_release=expected_release,
            binding=binding,
        ):
            return False
        prev_manifest = str(record["previous_release_manifest_sha256"])
        if prev_manifest == prior_manifest:
            seen_prior = True
        cursor_manifest = prev_manifest
        expected_release = str(record["previous_release_id"])
    return False


def _resolve_historical_operation(machine: Path, state: dict, binding: dict) -> dict | None:
    operation = _read_record(machine / "operations" / "history" / f"{state['operation_id']}.json")
    if operation is None:
        raise ConnectorAuthorityError("connector history for published state is missing")
    req = operation.get("request")
    op_manifest = req.get("release_manifest_sha256") if isinstance(req, dict) else None
    if op_manifest == binding.get("release_manifest_sha256"):
        require_connector_binding(operation, binding)
        if operation["operation_id"] != state["operation_id"] or operation["phase"] != "committed":
            raise ConnectorAuthorityError("connector history does not match its published state")
        return operation
    if (
        state["configured"] is not False
        or state["enabled"] is not False
        or state["tunnel_id"] is not None
        or not isinstance(op_manifest, str)
    ):
        require_connector_binding(operation, binding)
        raise ConnectorAuthorityError("connector history does not match the current installed binding")
    prior_binding = {**binding, "release_manifest_sha256": op_manifest}
    require_connector_binding(operation, prior_binding)
    if (
        operation["operation_id"] != state["operation_id"]
        or operation["phase"] != "committed"
        or operation["request"]["action"] != "remove"
    ):
        raise ConnectorAuthorityError("cross-release connector history must be a committed removal")
    if not _upgrade_chain_connects_manifests(machine, binding, prior_manifest=op_manifest):
        raise ConnectorAuthorityError("cross-release connector removal lacks committed upgrade provenance")
    return None


def connector_projection() -> dict:
    supported = os.name == "nt" and runtime_settings_service_owned()
    result = {"schema": "ticketbox-connector-projection-v1", "supported": supported,
        "binding": None, "public_origin_revision": 0, "state": None, "operation": None, "lifecycle_busy": False}
    if not supported:
        return result
    binding = {
        "install_id": os.environ.get("TICKETBOX_INSTALLATION_ID"),
        "dataset_id": os.environ.get("TICKETBOX_DATASET_ID"),
        "expected_restore_epoch": int(os.environ.get("TICKETBOX_EXPECTED_RESTORE_EPOCH", "-1")),
        "release_manifest_sha256": os.environ.get("TICKETBOX_RELEASE_MANIFEST_SHA256"),
    }
    projection = read_runtime_settings(RUNTIME_SETTINGS_PATH, service_owned=True)
    if projection is None:
        raise ConnectorAuthorityError("installed runtime projection is missing")
    machine = DATA_ROOT.parent.parent / "machine"
    state = _read_record(machine / "connectors" / "cloudflare" / "state.json")
    if state is not None:
        require_connector_state(state, binding)
    active = _read_record(machine / "operations" / "active.json")
    operation = None
    busy = active is not None
    if active is not None and active.get("kind") == "connector":
        require_connector_binding(active, binding)
        operation = active
    elif active is None and state is not None:
        operation = _resolve_historical_operation(machine, state, binding)
    return {**result, "binding": binding, "public_origin_revision": projection.public_origin_revision,
        "state": state, "operation": operation, "lifecycle_busy": busy}
