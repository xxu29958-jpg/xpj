from __future__ import annotations

import re

from ticketbox_lifecycle.adapters.ports import BindingPublisher, BindingReader
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    InstallationBinding,
    InstallRequest,
)


def ensure_runtime_binding(
    reader: BindingReader,
    publisher: BindingPublisher,
    request: InstallRequest,
) -> None:
    expected = binding_from_request(request)
    current = reader.read()
    if current is None:
        publisher.publish(expected)
        return
    require_binding_match(current, expected)


def require_runtime_binding(reader: BindingReader, request: InstallRequest) -> None:
    expected = binding_from_request(request)
    current = reader.read()
    if current is None:
        raise LifecycleViolation(
            "missing_binding",
            "committed operation has no installation.json",
        )
    require_binding_match(current, expected)


def require_binding_match(
    current: InstallationBinding,
    expected: InstallationBinding,
) -> None:
    if current != expected:
        raise LifecycleViolation(
            "identity_conflict",
            "installation.json does not match this operation's runtime selector",
        )


def binding_from_request(request: InstallRequest) -> InstallationBinding:
    if not request.install_id or not request.dataset_id:
        raise LifecycleViolation(
            "missing_identity",
            "install_id and dataset_id must be bound before publication",
        )
    if re.fullmatch(r"[0-9a-f]{64}", request.health_attestation_key) is None:
        raise LifecycleViolation(
            "missing_health_attestation",
            "health attestation key must be bound before publication",
        )
    return InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=request.install_id,
        dataset_id=request.dataset_id,
        expected_restore_epoch=0,
        data_root=request.data_root,
        active_release_id=request.target_release_id,
        previous_release_id=None,
        release_manifest_sha256=request.release_manifest_sha256,
        postgres_major=request.postgres_major,
        pg_service_name=request.pg_service_name,
        backend_service_name=request.backend_service_name,
        pg_port=request.pg_port,
        backend_port=request.backend_port,
        health_attestation_key=request.health_attestation_key,
    )
