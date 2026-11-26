from __future__ import annotations

import os
import re

from ticketbox_lifecycle.adapters.ports import AdapterBundle, PlatformAdapter
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import (
    APPLY_SEQUENCE,
    UPGRADE_SEQUENCE,
    ActiveOperation,
    ApplyStep,
    DurablePhase,
    HostObservation,
    InstallationBinding,
    InstallPlan,
    InstallRequest,
    UpgradeOperation,
)

_SEMVER = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
SUPPORTED_UPGRADE_SOURCE_RELEASES: dict[str, frozenset[str]] = {
    "1.3.0": frozenset({"1.2.1"}),
}


def plan_fresh_install(request: InstallRequest, observation: HostObservation) -> InstallPlan:
    if request.command not in {"install", "resume"}:
        raise LifecycleViolation("unsupported_command", f"fresh path cannot plan {request.command}")
    if observation.installation_present and request.command == "install":
        raise LifecycleViolation(
            "already_installed",
            "installation.json already exists; fresh install refuses to overwrite identity",
        )
    owned = (
        observation.active_operation_present
        and observation.active_operation_id == request.operation_id
    )
    if not owned:
        if observation.pgdata_present:
            raise LifecycleViolation(
                "unknown_existing_data",
                "pgdata exists without this operation; refusing to adopt foreign cluster state",
            )
        if observation.pg_service_present or observation.backend_service_present:
            raise LifecycleViolation(
                "scm_collision",
                "Ticketbox SCM records exist without this operation",
            )
    if observation.active_operation_present:
        if observation.active_operation_id != request.operation_id:
            raise LifecycleViolation(
                "operation_conflict",
                "a different active operation owns the machine",
            )
        if observation.active_phase == "committed":
            raise LifecycleViolation("already_committed", "active operation is already committed")
    steps = tuple(
        ApplyStep(name=name, adapter=_adapter_name(name)) for name in APPLY_SEQUENCE
    )
    return InstallPlan(kind="install", steps=steps)


def _adapter_name(step: str) -> str:
    return {
        "programdata_root": "files",
        "acl": "security",
        "postgres_initdb": "postgres",
        "scm": "scm",
        "start_postgres": "postgres",
        "roles_database": "postgres",
        "alembic": "alembic",
        "owner_claim": "dataset",
        "start_services": "scm",
        "health": "dataset",
    }[step]


def adapter_for_step(bundle: AdapterBundle, step: str) -> PlatformAdapter:
    return getattr(bundle, _adapter_name(step))


def _upgrade_adapter_name(step: str) -> str:
    return {
        "stop_services": "scm",
        "cold_backup": "files",
        "start_postgres": "postgres",
        "alembic": "alembic",
        "scm": "scm",
        "start_services": "scm",
        "health": "dataset",
    }[step]


def _semver_tuple(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch(version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _require_upgrade_binding_match(
    request: InstallRequest,
    binding: InstallationBinding,
) -> None:
    if (
        _norm_path(binding.data_root) != _norm_path(request.data_root)
        or binding.pg_service_name != request.pg_service_name
        or binding.backend_service_name != request.backend_service_name
        or binding.pg_port != request.pg_port
        or binding.backend_port != request.backend_port
        or binding.postgres_major != request.postgres_major
        or (request.install_id and request.install_id != binding.install_id)
        or (request.dataset_id and request.dataset_id != binding.dataset_id)
    ):
        raise LifecycleViolation(
            "upgrade_identity_mismatch",
            "upgrade request does not match existing installation binding",
        )


def _require_upgrade_active_match(
    request: InstallRequest,
    binding: InstallationBinding,
    active: ActiveOperation,
) -> None:
    if not isinstance(active, UpgradeOperation) or active.kind != "upgrade":
        raise LifecycleViolation("operation_conflict", "upgrade cannot resume another kind of operation")
    if active.operation_id != request.operation_id:
        raise LifecycleViolation("operation_conflict", "a different active operation owns the machine")
    if (
        active.target_release_id != request.target_release_id
        or active.release_manifest_sha256 != request.release_manifest_sha256
    ):
        raise LifecycleViolation("release_mismatch", "upgrade resume requires the same target release")
    if (
        active.install_id != binding.install_id
        or active.dataset_id != binding.dataset_id
        or active.expected_restore_epoch != binding.expected_restore_epoch
    ):
        raise LifecycleViolation("upgrade_identity_mismatch", "active upgrade disagrees with installation binding")
    published_target = (
        binding.active_release_id == active.target_release_id
        and binding.previous_release_id == active.previous_release_id
    )
    still_source = binding.active_release_id == active.previous_release_id
    if active.phase == "committed":
        if not published_target:
            raise LifecycleViolation("upgrade_binding_mismatch", "committed upgrade does not match installation.json")
    elif not (still_source or published_target):
        raise LifecycleViolation("upgrade_binding_mismatch", "installation.json release drifted during upgrade")


def plan_managed_upgrade(
    request: InstallRequest,
    observation: HostObservation,
    binding: InstallationBinding | None,
    active: ActiveOperation | None,
    *,
    supported_source_releases: frozenset[str] | None = None,
) -> InstallPlan:
    if request.command != "upgrade":
        raise LifecycleViolation("unsupported_command", f"upgrade path cannot plan {request.command}")
    if binding is None or not observation.installation_present:
        raise LifecycleViolation(
            "upgrade_installation_missing",
            "managed upgrade requires an existing verified installation.json",
        )
    if (
        not observation.pgdata_present
        or not observation.pg_service_present
        or not observation.backend_service_present
    ):
        raise LifecycleViolation(
            "upgrade_installation_incomplete",
            "managed upgrade requires existing pgdata and both installed services",
        )
    if observation.managed_connector_present:
        raise LifecycleViolation(
            "upgrade_managed_connector_active",
            "managed public connector is still configured; pause and remove it in Manager before upgrading",
        )
    _require_upgrade_binding_match(request, binding)
    if active is None:
        if observation.active_operation_present:
            raise LifecycleViolation("operation_conflict", "an active operation already owns the machine")
        if binding.active_release_id == request.target_release_id:
            raise LifecycleViolation("already_at_target_release", "installation is already running this release")
        current_ver = _semver_tuple(binding.active_release_id)
        target_ver = _semver_tuple(request.target_release_id)
        if current_ver is not None and target_ver is not None and target_ver < current_ver:
            raise LifecycleViolation("upgrade_downgrade_forbidden", "managed upgrade refuses release downgrade")
        allowed_sources = (
            supported_source_releases
            if supported_source_releases is not None
            else SUPPORTED_UPGRADE_SOURCE_RELEASES.get(request.target_release_id)
        )
        if allowed_sources is not None and binding.active_release_id not in allowed_sources:
            raise LifecycleViolation(
                "upgrade_source_release_unsupported",
                f"managed upgrade to {request.target_release_id} only supports source release(s): "
                + ", ".join(sorted(allowed_sources)),
            )
    else:
        _require_upgrade_active_match(request, binding, active)
    steps = tuple(
        ApplyStep(name=name, adapter=_upgrade_adapter_name(name)) for name in UPGRADE_SEQUENCE
    )
    return InstallPlan(kind="upgrade", steps=steps)


def phase_after(step: str) -> DurablePhase:
    if step in {
        "programdata_root",
        "acl",
        "postgres_initdb",
        "scm",
        "start_postgres",
        "roles_database",
        "alembic",
        "owner_claim",
    }:
        return "data_ready"
    if step in {"start_services", "health"}:
        return "release_activated"
    raise KeyError(step)
