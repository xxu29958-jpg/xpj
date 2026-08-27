from __future__ import annotations

from ticketbox_lifecycle.domain.planner import plan_fresh_install
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import (
    APPLY_SEQUENCE,
    REQUEST_SCHEMA,
    HostObservation,
    InstallRequest,
)


def _request() -> InstallRequest:
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="b" * 64,
        target_release_id="1.2.0+deadbeef",
        app_dir=r"C:\Program Files\Ticketbox",
        data_root=r"C:\ProgramData\Ticketbox\data",
        program_data_root=r"C:\ProgramData\Ticketbox",
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="a" * 64,
    )


def test_planner_is_pure_and_uses_fixed_sequence() -> None:
    observation = HostObservation(
        installation_present=False,
        active_operation_present=False,
        active_operation_id=None,
        active_phase=None,
        program_files_present=True,
        data_root_present=False,
    )
    plan = plan_fresh_install(_request(), observation)
    assert tuple(step.name for step in plan.steps) == APPLY_SEQUENCE


def test_planner_refuses_when_installation_already_exists() -> None:
    observation = HostObservation(
        installation_present=True,
        active_operation_present=False,
        active_operation_id=None,
        active_phase=None,
        program_files_present=True,
        data_root_present=True,
    )
    try:
        plan_fresh_install(_request(), observation)
        raise AssertionError("planner must refuse")
    except LifecycleViolation as exc:
        assert exc.code == "already_installed"


def test_planner_allows_resume_when_binding_exists_for_the_same_operation() -> None:
    request = _request()
    request = InstallRequest(**{**request.__dict__, "command": "resume"})
    observation = HostObservation(
        installation_present=True,
        active_operation_present=True,
        active_operation_id=request.operation_id,
        active_phase="release_activated",
        program_files_present=True,
        data_root_present=True,
        pgdata_present=True,
        pg_service_present=True,
        backend_service_present=True,
    )
    plan = plan_fresh_install(request, observation)
    assert tuple(step.name for step in plan.steps) == APPLY_SEQUENCE


def test_planner_refuses_foreign_pgdata_and_scm() -> None:
    request = _request()
    pgdata = HostObservation(
        installation_present=False,
        active_operation_present=False,
        active_operation_id=None,
        active_phase=None,
        program_files_present=True,
        data_root_present=True,
        pgdata_present=True,
    )
    try:
        plan_fresh_install(request, pgdata)
        raise AssertionError("foreign pgdata must not be adopted")
    except LifecycleViolation as exc:
        assert exc.code == "unknown_existing_data"
    scm = HostObservation(
        installation_present=False,
        active_operation_present=False,
        active_operation_id=None,
        active_phase=None,
        program_files_present=True,
        data_root_present=False,
        pg_service_present=True,
    )
    try:
        plan_fresh_install(request, scm)
        raise AssertionError("foreign SCM must not be adopted")
    except LifecycleViolation as exc:
        assert exc.code == "scm_collision"
