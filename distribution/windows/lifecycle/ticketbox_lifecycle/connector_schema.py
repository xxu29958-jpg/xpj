"""Closed, non-secret requests and journal records for the one connector profile."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields
from uuid import UUID

from ticketbox_lifecycle.errors import LifecycleError

PROFILE = "cloudflare-tunnel-v1"
REQUEST_SCHEMA = "ticketbox-connector-request-v1"
OPERATION_SCHEMA = "ticketbox-lifecycle-operation-v3"
STATE_SCHEMA = "ticketbox-connector-state-v1"
ACTIONS = frozenset({"configure", "reconnect", "set_enabled", "remove"})
PHASES = frozenset({"prepared", "applying", "committed", "failed_recoverable", "manual_intervention"})
STEPS = (None, "credential_prepared", "service_prepared", "intent_published", "host_applied")


@dataclass(frozen=True)
class ConnectorRequest:
    schema: str
    profile: str
    action: str
    operation_id: str
    install_id: str
    dataset_id: str
    expected_restore_epoch: int
    release_manifest_sha256: str
    expected_revision: int
    expected_credential_generation: int
    expected_enabled: bool
    expected_public_origin_revision: int
    initiator_sid: str
    desired_enabled: bool
    closing_operation_id: str | None = None
    closing_request_hash: str | None = None

    @property
    def request_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ConnectorOperation:
    schema: str
    kind: str
    impact: str
    operation_id: str
    request_hash: str
    request: ConnectorRequest
    phase: str
    completed_step: str | None
    result_code: str
    replaced_operation: ConnectorOperation | None = None


@dataclass(frozen=True)
class ConnectorState:
    schema: str
    profile: str
    install_id: str
    dataset_id: str
    expected_restore_epoch: int
    release_manifest_sha256: str
    revision: int
    credential_generation: int
    public_origin_revision: int
    enabled: bool
    configured: bool
    operation_id: str
    tunnel_id: str | None


def _closed(payload: object, model: type) -> dict:
    if not isinstance(payload, dict) or set(payload) != {field.name for field in fields(model)}:
        raise LifecycleError("connector_fields_invalid", "connector fields are not closed")
    return payload


def _identity(payload: dict) -> None:
    for key in ("operation_id", "install_id", "dataset_id"):
        try:
            value = payload[key]
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise LifecycleError("connector_identity_invalid", "connector identity must be canonical") from exc
    if re.fullmatch(r"[0-9a-f]{64}", str(payload["release_manifest_sha256"])) is None:
        raise LifecycleError("connector_manifest_invalid", "connector release digest is invalid")


def _counters(payload: dict, names: tuple[str, ...]) -> None:
    if any(type(payload[name]) is not int or not 0 <= payload[name] < 2**53 for name in names):
        raise LifecycleError("connector_revision_invalid", "connector counters must be nonnegative integers")


def parse_request(payload: object) -> ConnectorRequest:
    data = _closed(payload, ConnectorRequest)
    _identity(data)
    _counters(data, ("expected_restore_epoch", "expected_revision", "expected_credential_generation", "expected_public_origin_revision"))
    if data["schema"] != REQUEST_SCHEMA or data["profile"] != PROFILE or not isinstance(data["action"], str) or data["action"] not in ACTIONS:
        raise LifecycleError("connector_profile_invalid", "connector request profile or action is unsupported")
    if type(data["expected_enabled"]) is not bool or type(data["desired_enabled"]) is not bool:
        raise LifecycleError("connector_enabled_invalid", "connector authorization must be explicit")
    if re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", str(data["initiator_sid"])) is None:
        raise LifecycleError("connector_initiator_invalid", "connector initiator must be a Windows user SID")
    if (data["action"] == "remove" and data["desired_enabled"]) or (data["action"] == "reconnect" and not data["desired_enabled"]):
        raise LifecycleError("connector_action_invalid", "connector action contradicts its desired state")
    _require_closing_request(data)
    return ConnectorRequest(**data)


def _require_closing_request(data: dict) -> None:
    closing = data["closing_operation_id"]
    if closing is not None:
        try:
            if data["action"] != "remove" or not isinstance(closing, str) or str(UUID(closing)) != closing or closing == data["operation_id"]:
                raise ValueError
        except ValueError:
            raise LifecycleError("connector_close_invalid", "only an exact previous operation may be closed by removal") from None
        if re.fullmatch(r"[0-9a-f]{64}", str(data["closing_request_hash"])) is None:
            raise LifecycleError("connector_close_invalid", "closing requires the exact previous request digest")
    elif data["closing_request_hash"] is not None:
        raise LifecycleError("connector_close_invalid", "closing requires an operation identity")


def parse_operation(payload: object) -> ConnectorOperation:
    data = _closed(payload, ConnectorOperation)
    request = parse_request(data["request"])
    if (data["schema"], data["kind"], data["impact"]) != (OPERATION_SCHEMA, "connector", "connector_only"):
        raise LifecycleError("connector_operation_invalid", "connector journal profile is unsupported")
    if data["operation_id"] != request.operation_id or data["request_hash"] != request.request_hash:
        raise LifecycleError("connector_request_changed", "connector journal does not bind its immutable request")
    if not isinstance(data["phase"], str) or data["phase"] not in PHASES or data["completed_step"] not in STEPS:
        raise LifecycleError("connector_progress_invalid", "connector progress is unsupported")
    if data["phase"] == "committed" and data["completed_step"] != "host_applied":
        raise LifecycleError("connector_progress_invalid", "connector commit requires host readback")
    if not isinstance(data["result_code"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", data["result_code"]) is None:
        raise LifecycleError("connector_result_invalid", "connector result must be a non-secret code")
    previous = _parse_replaced_operation(data["replaced_operation"], request)
    return ConnectorOperation(**{**data, "request": request, "replaced_operation": previous})


def _parse_replaced_operation(previous: object, request: ConnectorRequest) -> ConnectorOperation | None:
    if previous is not None:
        if not isinstance(previous, dict) or previous.get("replaced_operation") is not None:
            raise LifecycleError("connector_close_invalid", "nested operation replacement is unsupported")
        previous = parse_operation(previous)
        if (request.closing_operation_id, request.closing_request_hash) != (previous.operation_id, previous.request_hash) or previous.phase == "committed" or previous.request.action == "remove":
            raise LifecycleError("connector_close_invalid", "closing journal does not match its exact unfinished predecessor")
    elif request.closing_operation_id is not None:
        raise LifecycleError("connector_close_invalid", "closing journal must preserve its original operation")
    return previous


def parse_state(payload: object) -> ConnectorState:
    data = _closed(payload, ConnectorState)
    _identity(data)
    _counters(data, ("expected_restore_epoch", "revision", "credential_generation", "public_origin_revision"))
    if data["schema"] != STATE_SCHEMA or data["profile"] != PROFILE:
        raise LifecycleError("connector_state_invalid", "connector state profile is unsupported")
    if type(data["enabled"]) is not bool or type(data["configured"]) is not bool or (data["enabled"] and not data["configured"]):
        raise LifecycleError("connector_state_invalid", "connector desired state is inconsistent")
    tunnel_id = data["tunnel_id"]
    try:
        if data["configured"]:
            if not isinstance(tunnel_id, str) or str(UUID(tunnel_id)) != tunnel_id:
                raise ValueError
        elif tunnel_id is not None:
            raise ValueError
    except ValueError as exc:
        raise LifecycleError("connector_state_invalid", "connector Tunnel identity is inconsistent") from exc
    return ConnectorState(**data)


def require_binding(request: ConnectorRequest, binding: object) -> None:
    if binding is None or any(getattr(binding, name, None) != getattr(request, name) for name in (
        "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
    )):
        raise LifecycleError("connector_binding_changed", "connector request no longer matches the installed instance")
