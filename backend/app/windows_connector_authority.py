"""A connector journal can preserve a binding, but can never authorize data startup."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

REQUEST_FIELDS = frozenset({
    "schema", "profile", "action", "operation_id", "install_id", "dataset_id", "expected_restore_epoch",
    "release_manifest_sha256", "expected_revision", "expected_credential_generation", "expected_enabled",
    "expected_public_origin_revision", "initiator_sid", "desired_enabled",
    "closing_operation_id", "closing_request_hash",
})
OPERATION_FIELDS = frozenset({
    "schema", "kind", "impact", "operation_id", "request_hash", "request", "phase", "completed_step", "result_code", "replaced_operation",
})
STATE_FIELDS = frozenset({
    "schema", "profile", "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
    "revision", "credential_generation", "public_origin_revision", "enabled", "configured", "operation_id", "tunnel_id",
})


class ConnectorAuthorityError(RuntimeError):
    pass


def require_connector_state(state: dict, binding: dict) -> None:
    if set(state) != STATE_FIELDS or state["schema"] != "ticketbox-connector-state-v1" or state["profile"] != "cloudflare-tunnel-v1":
        raise ConnectorAuthorityError("unsupported connector state profile")
    identity = {**state, "expected_revision": state["revision"], "expected_credential_generation": state["credential_generation"],
        "expected_public_origin_revision": state["public_origin_revision"]}
    _require_identity(identity)
    if any(state[key] != binding.get(key) for key in (
        "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
    )):
        raise ConnectorAuthorityError("connector state belongs to another installation or generation")
    if type(state["enabled"]) is not bool or type(state["configured"]) is not bool or state["enabled"] and not state["configured"]:
        raise ConnectorAuthorityError("connector desired state is inconsistent")
    tunnel_id = state["tunnel_id"]
    try:
        if state["configured"]:
            if not isinstance(tunnel_id, str) or str(UUID(tunnel_id)) != tunnel_id:
                raise ValueError
        elif tunnel_id is not None:
            raise ValueError
    except ValueError as exc:
        raise ConnectorAuthorityError("connector Tunnel identity is inconsistent") from exc


def require_connector_binding(active: dict, binding: dict | None) -> None:
    if set(active) != OPERATION_FIELDS or binding is None:
        raise ConnectorAuthorityError("connector operation requires a closed record and an installed binding")
    if (active["schema"], active["kind"], active["impact"]) != (
        "ticketbox-lifecycle-operation-v3", "connector", "connector_only",
    ):
        raise ConnectorAuthorityError("unsupported connector operation profile")
    request = active["request"]
    _require_request(request)
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if active["operation_id"] != request["operation_id"] or active["request_hash"] != digest:
        raise ConnectorAuthorityError("connector operation request changed")
    if any(request[field] != binding.get(field) for field in (
        "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
    )):
        raise ConnectorAuthorityError("connector operation does not match the current installed binding")
    _require_progress(active)
    previous = active["replaced_operation"]
    if previous is None:
        if request["closing_operation_id"] is not None:
            raise ConnectorAuthorityError("closing operation has no protected predecessor")
    else:
        if not isinstance(previous, dict) or previous.get("replaced_operation") is not None:
            raise ConnectorAuthorityError("nested operation replacement is unsupported")
        require_connector_binding(previous, binding)
        if ((request["closing_operation_id"], request["closing_request_hash"]) != (previous["operation_id"], previous["request_hash"])
            or previous["phase"] == "committed" or previous["request"]["action"] == "remove"):
            raise ConnectorAuthorityError("closing operation predecessor does not match")


def _require_progress(active: dict) -> None:
    if not isinstance(active["phase"], str) or active["phase"] not in {"prepared", "applying", "committed", "failed_recoverable", "manual_intervention"}:
        raise ConnectorAuthorityError("unsupported connector operation phase")
    if active["completed_step"] not in (None, "credential_prepared", "service_prepared", "intent_published", "host_applied"):
        raise ConnectorAuthorityError("unsupported connector operation progress")
    if active["phase"] == "committed" and active["completed_step"] != "host_applied":
        raise ConnectorAuthorityError("connector commit has no host readback")
    if not isinstance(active["result_code"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", active["result_code"]) is None:
        raise ConnectorAuthorityError("unsupported connector operation result")


def _require_request(request: object) -> None:
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ConnectorAuthorityError("connector operation request fields are not closed")
    if request["schema"] != "ticketbox-connector-request-v1" or request["profile"] != "cloudflare-tunnel-v1":
        raise ConnectorAuthorityError("unsupported connector request profile")
    if not isinstance(request["action"], str) or request["action"] not in {"configure", "reconnect", "set_enabled", "remove"}:
        raise ConnectorAuthorityError("unsupported connector request action")
    _require_identity(request)
    _require_authorization(request)
    _require_closing(request)


def _require_closing(request: dict) -> None:
    closing = request["closing_operation_id"]
    if closing is None:
        if request["closing_request_hash"] is not None:
            raise ConnectorAuthorityError("closing requires its operation identity")
        return
    try:
        if (request["action"] != "remove" or not isinstance(closing, str) or str(UUID(closing)) != closing
            or closing == request["operation_id"] or re.fullmatch(r"[0-9a-f]{64}", str(request["closing_request_hash"])) is None):
            raise ValueError
    except ValueError:
        raise ConnectorAuthorityError("invalid closing operation identity") from None


def _require_identity(request: dict) -> None:
    for field in ("operation_id", "install_id", "dataset_id"):
        try:
            value = request[field]
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError
        except (TypeError, ValueError, AttributeError) as exc:
            raise ConnectorAuthorityError("connector identity is not canonical") from exc
    if re.fullmatch(r"[0-9a-f]{64}", str(request["release_manifest_sha256"])) is None:
        raise ConnectorAuthorityError("connector release manifest is invalid")
    for field in ("expected_revision", "expected_credential_generation", "expected_restore_epoch", "expected_public_origin_revision"):
        if type(request[field]) is not int or not 0 <= request[field] < 2**53:
            raise ConnectorAuthorityError("connector revision is invalid")


def _require_authorization(request: dict) -> None:
    if re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", str(request["initiator_sid"])) is None:
        raise ConnectorAuthorityError("connector initiator SID is invalid")
    if type(request["expected_enabled"]) is not bool or type(request["desired_enabled"]) is not bool:
        raise ConnectorAuthorityError("connector enabled authorization is invalid")
    if (request["action"] == "remove" and request["desired_enabled"]) or (request["action"] == "reconnect" and not request["desired_enabled"]):
        raise ConnectorAuthorityError("connector action contradicts its desired state")
