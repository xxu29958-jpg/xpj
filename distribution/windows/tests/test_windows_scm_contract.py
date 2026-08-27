from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter
from ticketbox_lifecycle.runtime.windows_scm_observation import (
    FailureAction,
    ServiceConfiguration,
)
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest


class _Runner:
    def __init__(
        self,
        observed: dict[str, ServiceConfiguration],
        *,
        backend_running: bool = False,
    ) -> None:
        self.observed = observed
        self.calls: list[tuple[str, ...]] = []
        self.backend_running = backend_running

    def run(self, argv, **_kwargs) -> CompletedCommand:
        call = tuple(str(part) for part in argv)
        self.calls.append(call)
        if call[:2] == ("sc.exe", "query"):
            state = (
                "STATE : 4 RUNNING"
                if call[2] == "TicketboxBackend" and self.backend_running
                else "STATE : 1 STOPPED"
            )
            return CompletedCommand(call, 0, state, "")
        if call[:3] == ("sc.exe", "stop", "TicketboxBackend"):
            self.backend_running = False
            return CompletedCommand(call, 0, "STOP_PENDING", "")
        if call[:3] == ("sc.exe", "config", "TicketboxBackend") and "start=" in call:
            current = self.observed["TicketboxBackend"]
            start = call[call.index("start=") + 1]
            self.observed["TicketboxBackend"] = replace(
                current,
                start_type={"auto": 2, "demand": 3}[start],
            )
        return CompletedCommand(call, 0, "ok", "")


class _Security:
    def verify_pgdata_service_acl(self, *_args, **_kwargs) -> None:
        pass

    def verify_backend_runtime_authority(self, *_args, **_kwargs) -> None:
        pass


class _Observer:
    def __init__(self, observed: dict[str, ServiceConfiguration]) -> None:
        self.observed = observed

    def observe(self, name: str) -> ServiceConfiguration:
        return self.observed[name]


def _request(tmp_path: Path) -> InstallRequest:
    app = tmp_path / "app"
    release = app / "releases" / "1.2.0" / "backend"
    release.mkdir(parents=True)
    (app / "postgresql" / "bin").mkdir(parents=True)
    (app / "bin").mkdir()
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id="11111111-1111-4111-8111-111111111111",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        app_dir=str(app),
        data_root=str(tmp_path / "programdata" / "data"),
        program_data_root=str(tmp_path / "programdata"),
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        postgres_major=17,
        release_manifest_sha256="b" * 64,
        install_id="11111111-1111-4111-8111-111111111111",
        dataset_id="22222222-2222-4222-8222-222222222222",
    )


def _common(*, argv: tuple[str, ...], start_type: int, dependencies: tuple[str, ...], name: str) -> ServiceConfiguration:
    return ServiceConfiguration(
        service_type=0x10,
        start_type=start_type,
        error_control=1,
        argv=argv,
        load_order_group="",
        tag_id=0,
        dependencies=dependencies,
        account_sid="S-1-5-19",
        display_name=name,
        sid_type=1,
        failure_reset_seconds=3600,
        failure_actions=(
            FailureAction(action_type=1, delay_ms=5000),
            FailureAction(action_type=1, delay_ms=10000),
            FailureAction(action_type=1, delay_ms=60000),
        ),
        failure_reboot_message="",
        failure_command="",
        failure_actions_on_non_crash=False,
        delayed_auto_start=False,
        trigger_count=0,
    )


def _expected(request: InstallRequest, *, backend_start: int = 3) -> dict[str, ServiceConfiguration]:
    app = Path(request.app_dir)
    pg = _common(
        argv=(
            str(app / "postgresql" / "bin" / "pg_ctl.exe"),
            "runservice",
            "-N",
            request.pg_service_name,
            "-D",
            str(Path(request.data_root) / "pgdata"),
            "-w",
        ),
        start_type=2,
        dependencies=("RPCSS",),
        name=request.pg_service_name,
    )
    backend_exe = app / "releases" / request.target_release_id / "backend" / "ticketbox-backend.exe"
    backend = _common(
        argv=(
            str(app / "bin" / "shawl.exe"),
            "run",
            "--name",
            request.backend_service_name,
            "--cwd",
            str(backend_exe.parent),
            "--log-dir",
            str(Path(request.program_data_root) / "logs" / "backend"),
            "--env",
            f"TICKETBOX_DATA_DIR={Path(request.data_root) / 'app'}",
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
            str(backend_exe),
        ),
        start_type=backend_start,
        dependencies=(request.pg_service_name,),
        name=request.backend_service_name,
    )
    return {request.pg_service_name: pg, request.backend_service_name: backend}


def test_scm_verify_accepts_only_the_pinned_pg_ctl_and_shawl_contract(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request)
    adapter = WindowsScmAdapter(_Runner(observed), _Security(), _Observer(observed))

    adapter.verify(request, "scm")


def test_scm_verify_accepts_paths_canonicalized_by_shawl_add(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request)
    backend = observed[request.backend_service_name]
    argv = list(backend.argv)
    for option in ("--cwd", "--log-dir"):
        path_index = argv.index(option) + 1
        argv[path_index] = "\\\\?\\" + argv[path_index]
    observed[request.backend_service_name] = replace(backend, argv=tuple(argv))
    adapter = WindowsScmAdapter(_Runner(observed), _Security(), _Observer(observed))

    adapter.verify(request, "scm")


def test_scm_verify_rejects_extended_prefix_outside_shawl_path_options(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request)
    backend = observed[request.backend_service_name]
    observed[request.backend_service_name] = replace(
        backend,
        argv=(*backend.argv[:-1], "\\\\?\\" + backend.argv[-1]),
    )
    adapter = WindowsScmAdapter(_Runner(observed), _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match="argv"):
        adapter.verify(request, "scm")


@pytest.mark.parametrize(
    ("service", "field", "value"),
    [
        ("TicketboxPg", "service_type", 0x110),
        ("TicketboxPg", "error_control", 0),
        ("TicketboxPg", "argv", (r"C:\foreign.exe",)),
        ("TicketboxPg", "dependencies", ()),
        ("TicketboxPg", "account_sid", "S-1-5-18"),
        ("TicketboxPg", "sid_type", 0),
        ("TicketboxPg", "failure_reset_seconds", 0),
        ("TicketboxPg", "failure_actions", ()),
        ("TicketboxPg", "failure_reboot_message", "unexpected"),
        ("TicketboxPg", "failure_command", "unexpected.exe"),
        ("TicketboxPg", "failure_actions_on_non_crash", True),
        ("TicketboxPg", "delayed_auto_start", True),
        ("TicketboxPg", "trigger_count", 1),
        ("TicketboxBackend", "display_name", "Foreign"),
        ("TicketboxBackend", "load_order_group", "Foreign"),
        ("TicketboxBackend", "tag_id", 7),
    ],
)
def test_scm_verify_rejects_each_foreign_configuration_dimension(
    tmp_path: Path,
    service: str,
    field: str,
    value: object,
) -> None:
    request = _request(tmp_path)
    observed = _expected(request)
    observed[service] = replace(observed[service], **{field: value})
    adapter = WindowsScmAdapter(_Runner(observed), _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match=field):
        adapter.verify(request, "scm")


def test_scm_verify_does_not_case_fold_non_path_arguments(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request)
    backend = observed[request.backend_service_name]
    observed[request.backend_service_name] = replace(
        backend,
        argv=tuple(
            "TICKETBOX_OWNER_RECOVERY_CHANNEL=MANAGED_HOST"
            if value == "TICKETBOX_OWNER_RECOVERY_CHANNEL=managed_host"
            else value
            for value in backend.argv
        ),
    )
    adapter = WindowsScmAdapter(_Runner(observed), _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match="argv"):
        adapter.verify(request, "scm")


def test_existing_service_identity_is_observed_before_scm_mutation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    app = Path(request.app_dir)
    for binary in (
        app / "postgresql" / "bin" / "pg_ctl.exe",
        app / "bin" / "shawl.exe",
        app / "releases" / request.target_release_id / "backend" / "ticketbox-backend.exe",
    ):
        binary.touch()
    observed = _expected(request)
    pg = observed[request.pg_service_name]
    observed[request.pg_service_name] = replace(
        pg,
        argv=(r"C:\foreign.exe", *pg.argv),
    )
    runner = _Runner(observed)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match="argv"):
        adapter.apply(request, "scm")

    assert not any(call[:2] == ("sc.exe", "config") for call in runner.calls)


def test_initial_verify_accepts_backend_demand_but_final_promotion_requires_auto(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=3)
    runner = _Runner(observed)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    adapter.verify(request, "scm")
    adapter.enable_autostart(request)

    assert observed[request.backend_service_name].start_type == 2
    assert (
        "sc.exe",
        "config",
        request.backend_service_name,
        "start=",
        "auto",
    ) in runner.calls


def test_final_autostart_verification_does_not_reconfigure_an_exact_auto_service(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=2)
    runner = _Runner(observed)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    adapter.enable_autostart(request)

    assert not any(call[:2] == ("sc.exe", "config") for call in runner.calls)


def test_final_promotion_fails_closed_when_scm_readback_stays_demand(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=3)

    class _IgnoringRunner(_Runner):
        def run(self, argv, **_kwargs) -> CompletedCommand:
            call = tuple(str(part) for part in argv)
            self.calls.append(call)
            if call[:2] == ("sc.exe", "query"):
                return CompletedCommand(call, 0, "STATE : 1 STOPPED", "")
            return CompletedCommand(call, 0, "ok", "")

    adapter = WindowsScmAdapter(_IgnoringRunner(observed), _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match="start_type"):
        adapter.enable_autostart(request)


def test_backend_fence_demotes_autostart_before_stopping_exact_service(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=2)
    runner = _Runner(observed, backend_running=True)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    adapter.fence_backend(request)

    demand = ("sc.exe", "config", request.backend_service_name, "start=", "demand")
    stop = ("sc.exe", "stop", request.backend_service_name)
    assert observed[request.backend_service_name].start_type == 3
    assert runner.backend_running is False
    assert runner.calls.index(demand) < runner.calls.index(stop)


def test_backend_fence_refuses_foreign_service_before_mutation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=2)
    backend = observed[request.backend_service_name]
    observed[request.backend_service_name] = replace(backend, argv=(r"C:\foreign.exe",))
    runner = _Runner(observed, backend_running=True)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    with pytest.raises(LifecycleError, match="argv"):
        adapter.fence_backend(request)

    assert not any(call[:2] in {("sc.exe", "config"), ("sc.exe", "stop")} for call in runner.calls)


def test_backend_fence_does_not_treat_access_denied_as_absent(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=2)

    class _AccessDeniedRunner(_Runner):
        def run(self, argv, **_kwargs) -> CompletedCommand:
            call = tuple(str(part) for part in argv)
            self.calls.append(call)
            return CompletedCommand(call, 5, "", "[SC] OpenService FAILED 5")

    runner = _AccessDeniedRunner(observed, backend_running=True)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    with pytest.raises(LifecycleError) as raised:
        adapter.fence_backend(request)

    assert raised.value.code == "service_query_failed"
    assert runner.calls == [("sc.exe", "query", request.backend_service_name)]


def test_backend_fence_accepts_only_1060_as_absent(tmp_path: Path) -> None:
    request = _request(tmp_path)
    observed = _expected(request, backend_start=2)

    class _AbsentRunner(_Runner):
        def run(self, argv, **_kwargs) -> CompletedCommand:
            call = tuple(str(part) for part in argv)
            self.calls.append(call)
            return CompletedCommand(call, 1060, "", "service does not exist")

    runner = _AbsentRunner(observed)
    adapter = WindowsScmAdapter(runner, _Security(), _Observer(observed))

    adapter.fence_backend(request)

    assert runner.calls == [("sc.exe", "query", request.backend_service_name)]
