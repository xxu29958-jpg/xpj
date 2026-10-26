"""The existing bounded R1 sequence; platform mechanics are injected at its boundary."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import replace
from pathlib import Path

from ticketbox_lifecycle.adapters.restore import RestorePlatform, RestoreSource
from ticketbox_lifecycle.domain.binding import binding_from_request
from ticketbox_lifecycle.domain.operation import (
    LifecycleStores,
    failed_operation_result,
)
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import (
    OPERATION_SCHEMA,
    RESULT_SCHEMA,
    CommandResult,
    InstallRequest,
    RestoreOperation,
)


def restore(stores: LifecycleStores, request: InstallRequest, source_path: Path, digest: str,
            platform: RestorePlatform) -> CommandResult:
    """No resume or adoption: interruption keeps a closed, inspectable candidate."""
    stores.mutex.acquire()
    try:
        request = stores.shipment.bind_and_verify(request)
        observed = stores.observer.observe(request)
        if (observed.installation_present or observed.active_operation_present or observed.data_root_present
                or observed.pg_service_present or observed.backend_service_present):
            raise LifecycleError("restore_target_not_empty", "R1 requires a clean isolated installation target")
        stores.operations_write.require_fresh_inputs(request)
        with platform.open_source(request, source_path, digest) as source:
            return _restore_candidate(stores, request, source, platform)
    finally:
        stores.mutex.release()


def _restore_candidate(stores: LifecycleStores, request: InstallRequest, source: RestoreSource,
                       platform: RestorePlatform) -> CommandResult:
    bound = replace(request, install_id=str(uuid.uuid4()), dataset_id=source.identity["dataset_id"],
        health_attestation_key=secrets.token_hex(32))
    active = RestoreOperation(schema=OPERATION_SCHEMA, operation_id=bound.operation_id, kind="restore",
        request_hash=hashlib.sha256((source.digest + "\0" + bound.release_manifest_sha256).encode()).hexdigest(),
        target_release_id=bound.target_release_id, data_root=bound.data_root,
        release_manifest_sha256=bound.release_manifest_sha256, backend_port=bound.backend_port,
        phase="prepared", no_return_point=False, completed_step=None, install_id=bound.install_id,
        dataset_id=bound.dataset_id, schema_revision=bound.schema_revision, health_attestation_key=bound.health_attestation_key,
        expected_restore_epoch=source.identity["restore_epoch"] + 1)
    stores.operations_write.prepare(bound)
    stores.operations_write.publish_active(active)
    published = False
    try:
        platform.extract_data(bound, source)
        platform.prepare_data(bound, source)
        stores.adapters.files.apply(bound, "programdata_root")
        stores.adapters.files.verify(bound, "programdata_root")
        stores.adapters.security.apply(bound, "acl")
        stores.adapters.security.verify(bound, "acl")
        stores.adapters.scm.apply(bound, "scm")
        stores.adapters.scm.verify(bound, "scm")
        platform.rotate_credentials(bound, source)
        stores.adapters.postgres.verify(bound, "start_postgres")
        stores.adapters.postgres.verify(bound, "roles_database")
        stores.adapters.alembic.verify(bound, "alembic")
        pairing = platform.rebind_identity(bound, source, secret=stores.adapters.security.owner_bootstrap_secret(bound))
        # The protected operation admits only candidate health, with workers off.
        # Formal binding is published only after this verification succeeds.
        active = replace(active, phase="data_ready", completed_step="owner_claim", no_return_point=True)
        stores.operations_write.publish_active(active)
        stores.adapters.scm.apply(bound, "start_services")
        stores.adapters.dataset.apply(bound, "health")
        stores.adapters.dataset.verify(bound, "health")
        stores.adapters.scm.fence_backend(bound)
        active = replace(active, phase="release_activated", completed_step="health")
        stores.operations_write.publish_active(active)
        binding = replace(binding_from_request(bound), expected_restore_epoch=active.expected_restore_epoch)
        stores.binding_write.publish(binding)
        published = True
        active = replace(active, phase="committed", completed_step="health")
        stores.operations_write.publish_active(active)
        # Restart consumes the committed authority; the verified process cannot
        # accidentally turn into a business writer while verification is pending.
        stores.adapters.scm.apply(bound, "start_services")
        stores.adapters.dataset.apply(bound, "health")
        stores.adapters.dataset.verify(bound, "health")
        stores.adapters.scm.enable_autostart(bound)
        stores.operations_write.archive_committed(active)
        return CommandResult(schema=RESULT_SCHEMA, ok=True, command="restore", operation_id=bound.operation_id,
            phase="committed", code="restored", message="Same-environment restore committed; reconnect clients and reconcile old intents.",
            installation_published=True, pairing_code=pairing.pairing_code, pairing_expires_at=pairing.pairing_expires_at)
    except Exception as exc:
        primary = exc if isinstance(exc, (LifecycleError, OSError)) else LifecycleError(
            "restore_incomplete", "restore failed; preserve source and fenced candidate")
        return failed_operation_result(stores, request, active, bound,
            installation_published=published, primary=primary)
