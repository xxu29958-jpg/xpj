"""Read non-secret connector authority for the authenticated loopback Manager."""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import DATA_ROOT, RUNTIME_SETTINGS_PATH, runtime_settings_service_owned
from app.services import secure_file
from app.services.runtime_settings_store import read_runtime_settings
from app.windows_connector_authority import ConnectorAuthorityError, require_connector_binding, require_connector_state


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
        operation = _read_record(machine / "operations" / "history" / f"{state['operation_id']}.json")
        if operation is not None:
            require_connector_binding(operation, binding)
            if operation["operation_id"] != state["operation_id"] or operation["phase"] != "committed":
                raise ConnectorAuthorityError("connector history does not match its published state")
    return {**result, "binding": binding, "public_origin_revision": projection.public_origin_revision,
        "state": state, "operation": operation, "lifecycle_busy": busy}
