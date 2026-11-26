"""Bounded R1 (same-environment) and R2 (cross-machine) controlled recovery coordinator."""

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

_RESTORE_MODE_CANONICAL = {
    "same-environment": "same_environment",
    "same_environment": "same_environment",
    "cross-machine": "cross_machine",
    "cross_machine": "cross_machine",
}


def _normalize_restore_mode(mode: str) -> str:
    canonical = _RESTORE_MODE_CANONICAL.get(mode.strip().lower())
    if canonical is None:
        raise LifecycleError(
            "restore_mode_invalid",
            "restore mode must be same-environment or cross-machine",
        )
    return canonical


def _reconnect_guidance(canonical_mode: str) -> str:
    if canonical_mode == "cross_machine":
        return (
            "Cross-machine recovery completed with zero legacy WinCred/DPAPI dependency. "
            "Keep the previous machine isolated and revoke or retire any prior remote public tunnel before reconfiguring public connectivity. "
            "Pair Manager with the new owner pairing code, reconnect Android/Web to the new host generation, "
            "and reconcile any pending client outbox intents visibly without clearing client data or auto-resending unverified intents."
        )
    return (
        "Same-environment recovery completed. Pair Manager with the new owner pairing code, "
        "reconnect clients to the new host generation, and reconcile any pending client outbox intents visibly "
        "without clearing client data or auto-resending unverified intents."
    )


def restore(
    stores: LifecycleStores,
    request: InstallRequest,
    source_path: Path,
    digest: str,
    platform: RestorePlatform,
    *,
    restore_mode: str = "same-environment",
    source_isolated_confirmed: bool = True,
) -> CommandResult:
    """No resume or adoption: interruption keeps a closed, inspectable candidate."""
    canonical_mode = _normalize_restore_mode(restore_mode)
    if not source_isolated_confirmed:
        raise LifecycleError(
            "restore_source_isolation_required",
            "controlled recovery requires explicit source-isolation confirmation before opening writes",
        )
    stores.mutex.acquire()
    try:
        request = stores.shipment.bind_and_verify(request)
        observed = stores.observer.observe(request)
        if (observed.installation_present or observed.active_operation_present or observed.data_root_present
                or observed.pg_service_present or observed.backend_service_present
                or observed.managed_connector_present):
            raise LifecycleError(
                "restore_target_not_empty",
                "controlled recovery requires a clean isolated installation target without existing services or connectors",
            )
        stores.operations_write.require_fresh_inputs(request)
        with platform.open_source(request, source_path, digest) as source:
            return _restore_candidate(
                stores,
                request,
                source,
                platform,
                canonical_mode=canonical_mode,
                source_isolated_confirmed=source_isolated_confirmed,
            )
    finally:
        stores.mutex.release()


def _restore_candidate(
    stores: LifecycleStores,
    request: InstallRequest,
    source: RestoreSource,
    platform: RestorePlatform,
    *,
    canonical_mode: str,
    source_isolated_confirmed: bool,
) -> CommandResult:
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
        stores.adapters.scm.apply(bound, "start_services")
        stores.adapters.dataset.apply(bound, "health")
        stores.adapters.dataset.verify(bound, "health")
        stores.adapters.scm.enable_autostart(bound)
        stores.operations_write.archive_committed(active)
        revoked_summary = getattr(pairing, "revoked_credentials_summary", None)
        label = "Cross-machine" if canonical_mode == "cross_machine" else "Same-environment"
        return CommandResult(
            schema=RESULT_SCHEMA,
            ok=True,
            command="restore",
            operation_id=bound.operation_id,
            phase="committed",
            code="restored",
            message=f"{label} restore committed; reconnect clients and reconcile old intents.",
            installation_published=True,
            pairing_code=pairing.pairing_code,
            pairing_expires_at=pairing.pairing_expires_at,
            restore_mode=canonical_mode,
            client_generation=bound.install_id,
            restore_epoch=active.expected_restore_epoch,
            revoked_credentials_summary=revoked_summary,
            client_reconnect_guidance=_reconnect_guidance(canonical_mode),
            details={
                "source_isolated_confirmed": source_isolated_confirmed,
                "legacy_machine_material_required": False,
                "remote_public_entry_disposition": "reconfigure_after_source_isolation",
                "dataset_id": bound.dataset_id,
            },
        )
    except Exception as exc:
        primary = exc if isinstance(exc, (LifecycleError, OSError)) else LifecycleError(
            "restore_incomplete", "restore failed; preserve source and fenced candidate")
        return failed_operation_result(stores, request, active, bound,
            installation_published=published, primary=primary)
