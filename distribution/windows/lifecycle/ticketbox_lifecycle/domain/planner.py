from __future__ import annotations

from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import APPLY_SEQUENCE, ApplyStep, HostObservation, InstallPlan, InstallRequest


def plan_fresh_install(request: InstallRequest, observation: HostObservation) -> InstallPlan:
    if request.command not in {"install", "resume"}:
        raise LifecycleViolation("unsupported_command", f"fresh path cannot plan {request.command}")
    if observation.installation_present and request.command == "install":
        raise LifecycleViolation(
            "already_installed",
            "installation.json already exists; fresh install refuses to overwrite identity",
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
        "start_services": "scm",
        "health": "dataset",
    }[step]
