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


_RELEASE_ID_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")


def upgrade_binding(
    current: InstallationBinding,
    request: InstallRequest,
    *,
    previous_release_id: str | None = None,
) -> InstallationBinding:
    previous = previous_release_id if previous_release_id is not None else current.active_release_id
    if (
        not isinstance(previous, str)
        or _RELEASE_ID_PATTERN.fullmatch(previous) is None
        or previous == request.target_release_id
    ):
        raise LifecycleViolation(
            "invalid_release_transition",
            "upgrade requires a valid distinct previous_release_id",
        )
    if request.install_id != current.install_id or request.dataset_id != current.dataset_id:
        raise LifecycleViolation(
            "identity_conflict",
            "upgrade must preserve existing install_id and dataset_id",
        )
    if re.fullmatch(r"[0-9a-f]{64}", request.health_attestation_key) is None:
        raise LifecycleViolation(
            "missing_health_attestation",
            "health attestation key must be bound before publication",
        )
    return InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id=current.install_id,
        dataset_id=current.dataset_id,
        expected_restore_epoch=current.expected_restore_epoch,
        data_root=current.data_root,
        active_release_id=request.target_release_id,
        previous_release_id=previous,
        release_manifest_sha256=request.release_manifest_sha256,
        postgres_major=current.postgres_major,
        pg_service_name=current.pg_service_name,
        backend_service_name=current.backend_service_name,
        pg_port=current.pg_port,
        backend_port=current.backend_port,
        health_attestation_key=request.health_attestation_key,
    )
