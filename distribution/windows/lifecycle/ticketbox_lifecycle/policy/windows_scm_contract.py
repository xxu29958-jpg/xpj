from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.windows_scm_observation import (
    FailureAction,
    ServiceConfiguration,
)
from ticketbox_lifecycle.schemas import InstallRequest

SERVICE_WIN32_OWN_PROCESS = 0x10
SERVICE_AUTO_START = 2
SERVICE_DEMAND_START = 3
SERVICE_ERROR_NORMAL = 1
SERVICE_SID_TYPE_UNRESTRICTED = 1
SC_ACTION_RESTART = 1

_RESTART_ACTIONS = (
    FailureAction(SC_ACTION_RESTART, 5000),
    FailureAction(SC_ACTION_RESTART, 10000),
    FailureAction(SC_ACTION_RESTART, 60000),
)
_IMMUTABLE_IDENTITY_FIELDS = (
    "service_type",
    "error_control",
    "argv",
    "load_order_group",
    "tag_id",
    "display_name",
)


def expected_pg_service(request: InstallRequest) -> ServiceConfiguration:
    return _common(
        name=request.pg_service_name,
        start_type=SERVICE_AUTO_START,
        argv=(
            _service_path(Path(request.app_dir) / "postgresql" / "bin" / "pg_ctl.exe"),
            "runservice",
            "-N",
            request.pg_service_name,
            "-D",
            _service_path(Path(request.data_root) / "pgdata"),
            "-w",
        ),
        dependencies=("RPCSS",),
    )


def expected_backend_service(
    request: InstallRequest,
    *,
    start_type: int,
) -> ServiceConfiguration:
    backend = (
        Path(request.app_dir)
        / "releases"
        / request.target_release_id
        / "backend"
        / "ticketbox-backend.exe"
    )
    return _common(
        name=request.backend_service_name,
        start_type=start_type,
        argv=(
            _service_path(Path(request.app_dir) / "bin" / "shawl.exe"),
            "run",
            "--name",
            request.backend_service_name,
            "--cwd",
            _service_path(backend.parent),
            "--log-dir",
            _service_path(Path(request.program_data_root) / "logs" / "backend"),
            "--env",
            f"TICKETBOX_DATA_DIR={_service_path(Path(request.data_root) / 'app')}",
            "--env",
            f"TICKETBOX_INSTALLATION_ID={request.install_id}",
            "--env",
            f"TICKETBOX_DATASET_ID={request.dataset_id}",
            "--env",
            f"TICKETBOX_RELEASE_ID={request.target_release_id}",
            "--env",
            "TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host",
            "--env",
            f"TICKETBOX_PORT={request.backend_port}",
            "--",
            _service_path(backend),
        ),
        dependencies=(request.pg_service_name,),
    )


def require_service_configuration(
    name: str,
    observed: ServiceConfiguration,
    expected: ServiceConfiguration,
    *,
    allowed_start_types: frozenset[int],
) -> None:
    if observed.start_type not in allowed_start_types:
        _mismatch(name, "start_type")
    for field in fields(ServiceConfiguration):
        if field.name == "start_type":
            continue
        if not _field_matches(field.name, observed, expected):
            _mismatch(name, field.name)


def require_service_identity(
    name: str,
    observed: ServiceConfiguration,
    expected: ServiceConfiguration,
) -> None:
    for field in _IMMUTABLE_IDENTITY_FIELDS:
        if not _field_matches(field, observed, expected):
            raise LifecycleViolation(
                "scm_collision",
                f"service {name} has foreign {field}",
            )


def _common(
    *,
    name: str,
    start_type: int,
    argv: tuple[str, ...],
    dependencies: tuple[str, ...],
) -> ServiceConfiguration:
    return ServiceConfiguration(
        service_type=SERVICE_WIN32_OWN_PROCESS,
        start_type=start_type,
        error_control=SERVICE_ERROR_NORMAL,
        argv=argv,
        load_order_group="",
        tag_id=0,
        dependencies=dependencies,
        account_sid="S-1-5-19",
        display_name=name,
        sid_type=SERVICE_SID_TYPE_UNRESTRICTED,
        failure_reset_seconds=3600,
        failure_actions=_RESTART_ACTIONS,
        failure_reboot_message="",
        failure_command="",
        failure_actions_on_non_crash=False,
        delayed_auto_start=False,
        trigger_count=0,
    )


def _service_path(path: Path) -> str:
    value = os.path.abspath(os.fspath(path))
    return value.removeprefix("\\\\?\\")


def _normalize_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.replace("/", "\\") for value in argv)


def _field_matches(
    field: str,
    observed: ServiceConfiguration,
    expected: ServiceConfiguration,
) -> bool:
    actual_value = getattr(observed, field)
    expected_value = getattr(expected, field)
    if field == "argv":
        return _normalize_argv(actual_value) == _normalize_argv(expected_value)
    if field == "dependencies":
        return tuple(value.casefold() for value in actual_value) == tuple(
            value.casefold() for value in expected_value
        )
    return actual_value == expected_value


def _mismatch(name: str, field: str) -> None:
    raise LifecycleError(
        "scm_configuration_mismatch",
        f"service {name} has unexpected {field}",
    )
