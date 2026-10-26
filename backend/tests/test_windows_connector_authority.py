"""Backend and Lifecycle must agree before a connector journal can preserve startup."""

from __future__ import annotations

import importlib
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from app.windows_connector_authority import ConnectorAuthorityError, require_connector_binding


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "distribution/windows/lifecycle"))
    schema = importlib.import_module("ticketbox_lifecycle.connector_schema")
    request = schema.ConnectorRequest(schema.REQUEST_SCHEMA, schema.PROFILE, "configure",
        "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333", 0, "a" * 64, 0, 0, False, 7,
        "S-1-5-21-1-2-3-1001", True)
    operation = schema.ConnectorOperation(schema.OPERATION_SCHEMA, "connector", "connector_only",
        request.operation_id, request.request_hash, request, "prepared", None, "running")
    binding = {name: getattr(request, name) for name in (
        "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256")}
    return schema, asdict(operation), binding


@pytest.mark.parametrize("phase,step", [
    ("prepared", None), ("applying", "credential_prepared"), ("applying", "intent_published"),
    ("committed", "host_applied"), ("failed_recoverable", "service_prepared"), ("manual_intervention", None),
])
def test_lifecycle_wire_preserves_only_its_exact_installed_binding(wire, phase, step):
    schema, record, binding = wire
    record.update(phase=phase, completed_step=step)
    schema.parse_operation(record)
    require_connector_binding(record, binding)
    for key in binding:
        other = {**binding, key: "different"}
        with pytest.raises(ConnectorAuthorityError):
            require_connector_binding(record, other)


@pytest.mark.parametrize("section,field,value", [
    (None, "phase", []), (None, "completed_step", {}), (None, "kind", "install"),
    (None, "impact", "data"), (None, "result_code", "token=secret"),
    ("request", "action", []), ("request", "expected_revision", True),
    ("request", "desired_enabled", "true"), ("request", "initiator_sid", None),
])
def test_malformed_or_unknown_wire_fails_closed_in_both_consumers(wire, section, field, value):
    schema, record, binding = wire
    target = record[section] if section else record
    target[field] = value
    error = importlib.import_module("ticketbox_lifecycle.errors").LifecycleError
    with pytest.raises(error):
        schema.parse_operation(record)
    with pytest.raises(ConnectorAuthorityError):
        require_connector_binding(record, binding)


def test_exact_closure_preserves_startup_and_rejects_nested_or_changed_predecessor(wire):
    schema, record, binding = wire
    previous = schema.parse_operation(record)
    request = replace(previous.request, action="remove", operation_id="88888888-8888-4888-8888-888888888888",
        desired_enabled=False, closing_operation_id=previous.operation_id, closing_request_hash=previous.request_hash)
    closing = schema.ConnectorOperation(schema.OPERATION_SCHEMA, "connector", "connector_only", request.operation_id,
        request.request_hash, request, "prepared", None, "running", previous)
    payload = asdict(closing)
    schema.parse_operation(payload)
    require_connector_binding(payload, binding)
    for alteration in ("hash", "nested", "committed", "binding"):
        value = asdict(closing)
        prior = value["replaced_operation"]
        if alteration == "hash":
            prior["request_hash"] = "b" * 64
        elif alteration == "nested":
            prior["replaced_operation"] = record
        elif alteration == "committed":
            prior.update(phase="committed", completed_step="host_applied")
        else:
            prior["request"]["dataset_id"] = "99999999-9999-4999-8999-999999999999"
        with pytest.raises(ConnectorAuthorityError):
            require_connector_binding(value, binding)
