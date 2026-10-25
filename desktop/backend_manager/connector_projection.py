"""Closed, non-secret installed connector facts from the authenticated Backend."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from uuid import uuid4

from ticketbox_lifecycle.connector_schema import (
    PROFILE,
    REQUEST_SCHEMA,
    ConnectorOperation,
    ConnectorRequest,
    ConnectorState,
    parse_operation,
    parse_request,
    parse_state,
)
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.connector_profile import (
    FAILURE_ACTIONS,
    METRICS_PORT,
    SERVICE_ACCOUNT,
    SERVICE_NAME,
    service_argv,
)
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root, ticketbox_program_data_root
from ticketbox_lifecycle.schemas import InstallationBinding

from backend_manager.cloudflared_contract import ServiceFailureAction
from backend_manager.cloudflared_probe import ManagedConnectorExpectation
from backend_manager.product_data import (
    ProductDataError,
    _auth_headers,
    _opener,
    _read_json_response,
    _validated_loopback_origin,
)

_BINDING_FIELDS = ("install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256")


@dataclass(frozen=True)
class ConnectorProjection:
    binding: dict
    origin_revision: int
    state: ConnectorState | None
    operation: ConnectorOperation | None
    busy: bool

    def expectation(self, installed_binding: dict, backend_origin: str, public_origin: str | None) -> ManagedConnectorExpectation | None:
        if self.state is None or not self.state.configured:
            return None
        binding = InstallationBinding(**installed_binding)
        release = ticketbox_install_root() / "releases" / binding.active_release_id
        secrets = ticketbox_program_data_root() / "machine" / "connectors" / "cloudflare" / "secrets"
        return ManagedConnectorExpectation(SERVICE_NAME, service_argv(release, secrets, self.state.credential_generation),
            SERVICE_ACCOUNT, 2 if self.state.enabled else 4, 0xFFFFFFFF,
            tuple(ServiceFailureAction(action.action_type, action.delay_ms) for action in FAILURE_ACTIONS),
            METRICS_PORT, self.state.tunnel_id, backend_origin, public_origin or "", binding)

    @property
    def authority_key(self) -> tuple:
        state, operation = self.state, self.operation
        return (tuple(self.binding[name] for name in _BINDING_FIELDS), self.origin_revision,
            (state.revision, state.credential_generation, state.enabled, state.configured) if state else None,
            (operation.request_hash, operation.phase, operation.completed_step) if operation else None, self.busy)

    def request(self, action: str, *, enabled: bool, sid: str) -> ConnectorRequest:
        closing_id = closing_hash = None
        if self.busy:
            if self.operation is None or self.operation.phase == "committed":
                raise ProductDataError("本机维护正在完成，请稍后重试。")
            original = self.operation.request
            if action == "remove" and original.action != "remove":
                closing_id, closing_hash = original.operation_id, original.request_hash
            elif (original.action, original.desired_enabled, original.initiator_sid) != (action, enabled, sid):
                raise ProductDataError("上次操作尚未完成，请先继续该操作。")
            else:
                return original
        state = self.state
        return parse_request({"schema": REQUEST_SCHEMA, "profile": PROFILE, "action": action,
            "operation_id": str(uuid4()), **self.binding, "expected_revision": state.revision if state else 0,
            "expected_credential_generation": state.credential_generation if state else 0,
            "expected_enabled": state.enabled if state else False, "expected_public_origin_revision": self.origin_revision,
            "initiator_sid": sid, "desired_enabled": enabled,
            "closing_operation_id": closing_id, "closing_request_hash": closing_hash})


def parse_projection(payload: dict, installed_binding: dict) -> ConnectorProjection:
    expected_fields = {"schema", "supported", "binding", "public_origin_revision", "state", "operation", "lifecycle_busy"}
    if (set(payload) != expected_fields or payload["schema"] != "ticketbox-connector-projection-v1"
        or payload["supported"] is not True or type(payload["lifecycle_busy"]) is not bool):
        raise ProductDataError("当前安装尚未提供受管公网连接。")
    binding = {name: installed_binding.get(name) for name in _BINDING_FIELDS}
    if payload["binding"] != binding:
        raise ProductDataError("安装身份发生变化，请重新打开管理器。")
    revision = payload["public_origin_revision"]
    if type(revision) is not int or not 0 <= revision < 2**53:
        raise ProductDataError("无法确认当前公网设置。")
    try:
        state = parse_state(payload["state"]) if payload["state"] is not None else None
        operation = parse_operation(payload["operation"]) if payload["operation"] is not None else None
    except LifecycleError:
        raise ProductDataError("无法确认当前连接记录。") from None
    _require_record_bindings(binding, state, operation)
    return ConnectorProjection(binding, revision, state, operation, payload["lifecycle_busy"])


def _require_record_bindings(binding: dict, state: ConnectorState | None, operation: ConnectorOperation | None) -> None:
    for record in (state, operation.request if operation else None):
        if record is not None and any(getattr(record, name) != binding[name] for name in _BINDING_FIELDS):
            raise ProductDataError("连接记录不属于当前安装。")


def read_connector_projection(backend_origin: str, token: str, installed_binding: dict) -> ConnectorProjection:
    _validated_loopback_origin(backend_origin)
    request = urllib.request.Request(f"{backend_origin.rstrip('/')}/desktop/public-connectivity",
        headers=_auth_headers(token), method="GET")
    return parse_projection(_read_json_response(_opener(), request, timeout_seconds=1.0), installed_binding)
