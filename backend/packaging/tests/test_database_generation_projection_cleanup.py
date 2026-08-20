import shutil
import subprocess
import uuid
from pathlib import Path

import _database_generation_projection_cleanup as cleanup
import pytest

pytestmark = pytest.mark.xdist_group(name="windows_postgresql_runtime")


def _assert_cleanup_order(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    pg_bin: Path,
    shawl: Path,
    service_name: str,
    observations: tuple[bool | BaseException, ...],
    service_results: tuple[str | None, ...],
    postgres_results: tuple[str | None, ...],
    expected_order: list[str],
) -> None:
    order: list[str] = []
    pending_observations = iter(observations)
    pending_service_results = iter(service_results)
    pending_postgres_results = iter(postgres_results)

    def observe_service(**_kwargs: object) -> bool:
        order.append("inspect")
        observed = next(pending_observations)
        if isinstance(observed, BaseException):
            raise observed
        return observed

    def stop_postgres(*_args: object, **_kwargs: object) -> str | None:
        order.append("postgres")
        return next(pending_postgres_results)

    def clean_service(**_kwargs: object) -> str | None:
        order.append("service")
        return next(pending_service_results)

    def remove_root(*_args: object, **kwargs: object) -> None:
        assert kwargs["host_cleanup_error"] is None
        order.append("root")

    with monkeypatch.context() as patch:
        patch.setattr(cleanup, "projection_service_exists", observe_service)
        patch.setattr(cleanup, "ensure_projection_pg_stopped", stop_postgres)
        patch.setattr(cleanup, "ensure_projection_one_shot_service_absent", clean_service)
        patch.setattr(cleanup, "remove_projection_machine_work_root", remove_root)
        assert cleanup.cleanup_projection_runtime(
            engine="powershell.exe",
            pg_bin=pg_bin,
            shawl=shawl,
            service_name=service_name,
            work_root=tmp_path / "work-root",
        ) == (None, None, None)
    assert order == expected_order


def test_projection_machine_cleanup_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixture_source = (
        Path(__file__).with_name("powershell_fixtures") / "database_generation_projection_postgres.ps1"
    ).read_text(encoding="utf-8-sig")
    assert (
        '"create", $OneShotServiceName,\n'
        '            "binPath=", $crashImagePath,\n'
        '            "start=", "demand",\n'
        '            "obj=", "NT AUTHORITY\\LocalService"'
    ) in fixture_source
    assert (
        "Set-TicketboxServiceIdentityContract `\n"
        "            -Name $OneShotServiceName `\n"
        '            -LogonAccount "NT AUTHORITY\\LocalService" `\n'
        '            -SidType "unrestricted"'
    ) in fixture_source

    with monkeypatch.context() as patch:
        patch.setenv("PROGRAMDATA", str(tmp_path))
        work_root = tmp_path / f"TicketboxProjectionTest-{uuid.uuid4().hex}"
        work_root.mkdir()
        removed: list[Path] = []
        remove_tree = shutil.rmtree

        def remove_spy(path: Path) -> None:
            removed.append(path)
            remove_tree(path)

        patch.setattr(shutil, "rmtree", remove_spy)
        assert cleanup.remove_projection_machine_work_root(work_root, host_cleanup_error="unconfirmed") is None
        assert work_root.is_dir() and removed == []
        assert cleanup.remove_projection_machine_work_root(work_root, host_cleanup_error=None) is None
        assert not work_root.exists() and removed == [work_root]

        invalid_roots = (
            tmp_path.parent / f"TicketboxProjectionTest-{uuid.uuid4().hex}",
            tmp_path / uuid.uuid4().hex,
            tmp_path / "TicketboxProjectionTest-not-a-uuid",
        )
        for unexpected in invalid_roots:
            assert (
                cleanup.remove_projection_machine_work_root(unexpected, host_cleanup_error=None)
                == f"refused to remove unexpected projection work root: {unexpected}"
            )
        assert removed == [work_root]

    stop_root = tmp_path / "projection-stop-failure"
    (stop_root / "pgdata").mkdir(parents=True)
    stop_calls = 0

    def stop_run_stub(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal stop_calls
        stop_calls += 1
        if stop_calls == 1:
            return subprocess.CompletedProcess([], 0)
        raise OSError("native stop failed")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", stop_run_stub)
        stop_error = cleanup.ensure_projection_pg_stopped(tmp_path / "pg-bin", stop_root)
    assert stop_error == f"could not stop projection PostgreSQL at {stop_root / 'pgdata'}: native stop failed"

    service_name = f"TicketboxProjection-{uuid.uuid4().hex}"
    shawl_path = tmp_path / "shawl.exe"
    pg_bin_path = tmp_path / "pg-bin"
    captured: list[object] = []

    def capture_command(args: list[object], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured[:] = args
        return subprocess.CompletedProcess(args, 0, "", "")

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", capture_command)
        assert (
            cleanup.ensure_projection_one_shot_service_absent(
                engine="powershell.exe",
                service_name=service_name,
                shawl=shawl_path,
                pg_bin=pg_bin_path,
            )
            is None
        )
    script = str(captured[-1])
    assert (
        "-ExpectedRuntimeExecutables @('" + str(shawl_path) + "', '" + str(pg_bin_path / "postgres.exe") + "')"
    ) in script

    for raised_error, result in (
        (OSError("service cleanup launch failed"), None),
        (subprocess.TimeoutExpired(["powershell.exe"], 75), None),
        (None, subprocess.CompletedProcess([], 9, "cleanup stdout", "cleanup stderr")),
    ):

        def service_run_stub(
            *_args: object,
            _raised_error: BaseException | None = raised_error,
            _result: subprocess.CompletedProcess[str] | None = result,
            **_kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            if _raised_error is not None:
                raise _raised_error
            assert _result is not None
            return _result

        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", service_run_stub)
            service_error = cleanup.ensure_projection_one_shot_service_absent(
                engine="powershell.exe",
                service_name=service_name,
                shawl=shawl_path,
                pg_bin=pg_bin_path,
            )
        assert service_error is not None and service_name in service_error

    with monkeypatch.context() as patch:
        cleanup_events: list[str] = []

        def postgres_cleanup_stub(*_args: object, **_kwargs: object) -> str:
            cleanup_events.append("postgres")
            return "postgres cleanup failed"

        def service_cleanup_stub(**_kwargs: object) -> str:
            cleanup_events.append("service")
            return "service cleanup failed"

        def service_exists_stub(**_kwargs: object) -> bool:
            cleanup_events.append("inspect")
            return True

        patch.setattr(cleanup, "ensure_projection_pg_stopped", postgres_cleanup_stub)
        patch.setattr(cleanup, "ensure_projection_one_shot_service_absent", service_cleanup_stub)
        patch.setattr(cleanup, "projection_service_exists", service_exists_stub)

        def root_stub(_work_root: Path, *, host_cleanup_error: str | None) -> str:
            cleanup_events.append("root")
            assert host_cleanup_error == "postgres cleanup failed; service cleanup failed"
            return "root cleanup failed"

        patch.setattr(cleanup, "remove_projection_machine_work_root", root_stub)
        errors = cleanup.cleanup_projection_runtime(
            engine="powershell.exe",
            pg_bin=pg_bin_path,
            shawl=shawl_path,
            service_name=service_name,
            work_root=tmp_path / "work-root",
        )
    assert errors == ("postgres cleanup failed", "service cleanup failed", "root cleanup failed")
    assert cleanup_events == ["inspect", "service", "postgres", "service", "root"]

    _assert_cleanup_order(
        monkeypatch,
        tmp_path=tmp_path,
        pg_bin=pg_bin_path,
        shawl=shawl_path,
        service_name=service_name,
        observations=(True, False),
        service_results=(None,),
        postgres_results=(None,),
        expected_order=["inspect", "service", "inspect", "postgres", "root"],
    )
    _assert_cleanup_order(
        monkeypatch,
        tmp_path=tmp_path,
        pg_bin=pg_bin_path,
        shawl=shawl_path,
        service_name=service_name,
        observations=(False, False),
        service_results=(None,),
        postgres_results=(None,),
        expected_order=["inspect", "postgres", "service", "inspect", "root"],
    )
    _assert_cleanup_order(
        monkeypatch,
        tmp_path=tmp_path,
        pg_bin=pg_bin_path,
        shawl=shawl_path,
        service_name=service_name,
        observations=(RuntimeError("transient SCM observation failure"), False),
        service_results=("blocked before postmaster cleanup", None),
        postgres_results=(None,),
        expected_order=["inspect", "service", "postgres", "service", "inspect", "root"],
    )
    _assert_cleanup_order(
        monkeypatch,
        tmp_path=tmp_path,
        pg_bin=pg_bin_path,
        shawl=shawl_path,
        service_name=service_name,
        observations=(True, False),
        service_results=("transient service cleanup failure", None),
        postgres_results=("postmaster still live", None),
        expected_order=["inspect", "service", "postgres", "service", "inspect", "postgres", "root"],
    )
    primary = RuntimeError("projection primary sentinel")
    with pytest.raises(RuntimeError) as raised:
        cleanup.raise_projection_primary_failure(primary, errors)
    assert raised.value is primary
    assert raised.value.__notes__ == [
        "postgres cleanup failed",
        "service cleanup failed",
        "root cleanup failed",
    ]
