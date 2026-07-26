from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from tests._infra.ci_gap import load_ci_gap_audit

_ROOT = Path(__file__).resolve().parents[2]
_CI_JOB_TIMEOUT_CEILING_MINUTES = 12
_SCOPE_IF = (
    "${{ always() && !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.postgres != 'false') }}"
)
_LANE_RUNNER = "scripts.run_postgres_pytest_lane"
_SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"


def _workflow_jobs(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded.get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _steps(job: dict[str, object]) -> dict[str, dict[str, object]]:
    return {step["name"]: step for step in job["steps"]}


def _assert_qualification_step(
    job: dict[str, object],
    step: dict[str, object],
    *,
    resolves_audit_base: bool = False,
) -> None:
    assert step["id"] == "qualification"
    assert step["env"]["EXPECTED_SHA"] == "${{ github.sha }}"
    assert step["env"]["SOURCE_SHA"] == ("${{ github.event.pull_request.head.sha || github.sha }}")
    tokens = shlex.split(step["run"], posix=True)
    assert tokens[:3] == ["python", "-E", "-S"]
    defaults = job.get("defaults", {})
    run_defaults = defaults.get("run", {}) if isinstance(defaults, dict) else {}
    working_directory = run_defaults.get("working-directory", "") if isinstance(run_defaults, dict) else ""
    reporter = (_ROOT / str(working_directory) / tokens[3]).resolve()
    assert reporter == (_ROOT / "backend" / "scripts" / "report_qualification_sha.py").resolve()
    expected_arguments = [
        "--expected",
        "$EXPECTED_SHA",
        "--source",
        "$SOURCE_SHA",
        "--output",
        "$GITHUB_OUTPUT",
    ]
    if resolves_audit_base:
        expected_arguments.append("--audit-base")
    assert tokens[4:] == expected_arguments


def _assert_managed_python_precedes(job: dict[str, object], *python_step_names: str) -> None:
    step_names = [step["name"] for step in job["steps"]]
    setup = _steps(job)["Set up Python"]
    assert setup["uses"] == _SETUP_PYTHON
    assert setup["with"]["python-version"] == "3.11"
    setup_index = step_names.index("Set up Python")
    assert all(setup_index < step_names.index(name) for name in python_step_names)


def _assert_bounded_timeout(job: dict[str, object]) -> None:
    timeout = job["timeout-minutes"]
    assert isinstance(timeout, int)
    assert 0 < timeout <= _CI_JOB_TIMEOUT_CEILING_MINUTES


def _assert_no_continue_on_error(job: dict[str, object]) -> None:
    assert "continue-on-error" not in job
    for step in job["steps"]:
        assert "continue-on-error" not in step


def _assert_postgres_job_contract(
    job: dict[str, object],
    *,
    ordinary: bool,
) -> None:
    assert "env" not in job
    matrix: dict[str, object] = {
        "postgres": "${{ fromJSON(needs.scope.outputs.postgres_matrix).include }}",
    }
    if ordinary:
        matrix["shard"] = [
            {"index": 0, "count": 2, "label": "1/2"},
            {"index": 1, "count": 2, "label": "2/2"},
        ]
    assert job["strategy"] == {
        "fail-fast": False,
        "matrix": matrix,
    }
    service = job["services"]["postgres"]
    assert service["image"] == "${{ matrix.postgres['postgres-image'] }}"
    assert service["env"] == {
        "POSTGRES_PASSWORD": "xpj-ci-${{ github.run_id }}-${{ github.run_attempt }}",
        "POSTGRES_HOST_AUTH_METHOD": "scram-sha-256",
        "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256",
    }
    assert service["ports"] == ["5432/tcp"]


def _assert_checkout_independent_passfile_cleanup(step: dict[str, object]) -> None:
    assert step["if"] == "${{ always() }}"
    assert step["working-directory"] == "${{ runner." + "te" + "mp }}"
    assert str(step["run"]).splitlines() == [
        'if [ -n "${PGPASSFILE:-}" ]; then',
        '  rm -f -- "$PGPASSFILE"',
        "fi",
    ]


def _expected_lane_runner(
    *,
    lane: str,
    workers: int,
    shard_index: str | None,
    shard_count: str | None,
) -> list[str]:
    command = [
        "./.ci-venv/bin/python",
        "-m",
        _LANE_RUNNER,
        "--lane",
        lane,
        "--workers",
        str(workers),
    ]
    if shard_index is not None and shard_count is not None:
        command.extend(
            (
                "--shard-index",
                shard_index,
                "--shard-count",
                shard_count,
            )
        )
    return command


def _assert_lane(
    job: object,
    *,
    name: str,
    prepare_step: str,
    prepare_roles: tuple[str, ...],
    runner_step: str,
    lane: str,
    workers: int,
    shard_index: str | None = None,
    shard_count: str | None = None,
) -> None:
    assert isinstance(job, dict)
    assert job["name"] == name
    assert job["needs"] == "scope"
    assert job["if"] == _SCOPE_IF
    _assert_postgres_job_contract(job, ordinary=shard_index is not None)
    assert job["outputs"]["qualification_sha"] == "${{ steps.qualification.outputs.sha }}"
    assert job["outputs"]["qualification_source_sha"] == ("${{ steps.qualification.outputs.source_sha }}")
    _assert_bounded_timeout(job)
    _assert_no_continue_on_error(job)
    _assert_managed_python_precedes(job, "Verify qualification SHA", "Load test PostgreSQL contract")
    steps = _steps(job)
    _assert_qualification_step(job, steps["Verify qualification SHA"])

    load_step = steps["Load test PostgreSQL contract"]
    assert load_step["env"] == {
        "TEST_POSTGRES_PASSWORD": "xpj-ci-${{ github.run_id }}-${{ github.run_attempt }}",
        "TEST_POSTGRES_APPLICATION_PASSWORD": ("xpj-app-${{ github.run_id }}-${{ github.run_attempt }}"),
    }
    load = shlex.split(load_step["run"], posix=True)
    assert load[:5] == ["python", "-E", "-S", "-m", "scripts.write_test_postgres_env"]
    assert load[5:] == [
        "--host",
        "localhost",
        "--port",
        "${{ job.services.postgres.ports[5432] }}",
        "--admin-user",
        "postgres",
        "--admin-password-env",
        "TEST_POSTGRES_PASSWORD",
        "--application-password-env",
        "TEST_POSTGRES_APPLICATION_PASSWORD",
        "--passfile",
        "$RUNNER_TEMP/xpj-pgpass-${GITHUB_RUN_ID}-${GITHUB_JOB}",
        "--output",
        "$GITHUB_ENV",
    ]
    prepare = shlex.split(steps[prepare_step]["run"], posix=True)
    assert steps[prepare_step]["env"] == {
        "XPJ_TEST_APPLICATION_PASSWORD": ("xpj-app-${{ github.run_id }}-${{ github.run_attempt }}")
    }
    assert prepare[:3] == [
        "./.ci-venv/bin/python",
        "-m",
        "scripts.prepare_test_postgres_databases",
    ]
    assert prepare[3:] == [
        *[item for role in prepare_roles for item in ("--role", role)],
        "--expected-major",
        "${{ matrix.postgres['postgres-major'] }}",
    ]
    assert shlex.split(steps[runner_step]["run"], posix=True) == (
        _expected_lane_runner(
            lane=lane,
            workers=workers,
            shard_index=shard_index,
            shard_count=shard_count,
        )
    )
    _assert_checkout_independent_passfile_cleanup(
        steps["Remove PostgreSQL passfile"]
    )


def _assert_recovery_job(job: object) -> None:
    assert isinstance(job, dict)
    assert job["name"] == (
        "Backend PostgreSQL / smoke + recovery "
        "(PG ${{ matrix.postgres['postgres-major'] }})"
    )
    assert job["needs"] == "scope"
    assert job["if"] == _SCOPE_IF
    _assert_postgres_job_contract(job, ordinary=False)
    _assert_bounded_timeout(job)
    _assert_no_continue_on_error(job)
    _assert_managed_python_precedes(job, "Verify qualification SHA", "Load test PostgreSQL contract")
    steps = _steps(job)
    _assert_qualification_step(job, steps["Verify qualification SHA"])
    assert steps["Load test PostgreSQL contract"]["env"] == {
        "TEST_POSTGRES_PASSWORD": "xpj-ci-${{ github.run_id }}-${{ github.run_attempt }}",
        "TEST_POSTGRES_APPLICATION_PASSWORD": ("xpj-app-${{ github.run_id }}-${{ github.run_attempt }}"),
    }
    client_install = steps["Install supported PostgreSQL client"]["run"]
    assert "postgresql-client-${{ matrix.postgres['postgres-major'] }}" in client_install
    assert "/usr/lib/postgresql/${{ matrix.postgres['postgres-major'] }}/bin" in client_install
    assert "postgresql-client-17" not in client_install
    assert "/usr/lib/postgresql/17/bin" not in client_install
    prepare = shlex.split(steps["Prepare smoke and recovery databases"]["run"])
    assert steps["Prepare smoke and recovery databases"]["env"] == {
        "XPJ_TEST_APPLICATION_PASSWORD": ("xpj-app-${{ github.run_id }}-${{ github.run_attempt }}")
    }
    assert prepare == [
        "./.ci-venv/bin/python",
        "-m",
        "scripts.prepare_test_postgres_databases",
        "--role",
        "smoke",
        "--role",
        "restore",
        "--expected-major",
        "${{ matrix.postgres['postgres-major'] }}",
    ]
    assert steps["PostgreSQL end-to-end smoke (ADR-0041)"]["run"] == ("./.ci-venv/bin/python scripts/smoke_test.py")
    assert (
        steps["PostgreSQL backup/restore recovery drill (ADR-0041 phase-2)"]["run"]
        == "./.ci-venv/bin/python scripts/postgres_backup_drill.py"
    )
    scripts = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert _LANE_RUNNER not in scripts
    assert " -m pytest " not in scripts
    _assert_checkout_independent_passfile_cleanup(
        steps["Remove PostgreSQL passfile"]
    )


def _assert_no_postgres_password_leaks(jobs: dict[str, object]) -> None:
    for job_name in (
        "backend_postgres_ordinary",
        "backend_postgres_real_db",
        "backend_postgres_recovery",
    ):
        job = jobs[job_name]
        assert "TEST_POSTGRES_PASSWORD" not in job.get("env", {})
        loader = _steps(job)["Load test PostgreSQL contract"]
        assert tuple(loader["env"]) == (
            "TEST_POSTGRES_PASSWORD",
            "TEST_POSTGRES_APPLICATION_PASSWORD",
        )
        serialized = repr(job)
        assert "PGPASSWORD" not in serialized
        assert "postgres:postgres@" not in serialized


def _assert_postgres_aggregator(job: object) -> None:
    assert isinstance(job, dict)
    assert job["needs"] == [
        "scope",
        "backend_postgres_ordinary",
        "backend_postgres_real_db",
        "backend_postgres_recovery",
    ]
    assert job["if"] == "${{ always() }}"
    _assert_no_continue_on_error(job)
    _assert_managed_python_precedes(job, "Verify qualification SHA", "Enforce PostgreSQL lane results")
    enforcement = _steps(job)["Enforce PostgreSQL lane results"]
    assert enforcement["run"] == (
        "python -E -S backend/scripts/verify_scoped_ci_results.py "
        "--label PostgreSQL --scope-key POSTGRES_SCOPE "
        "--lane ORDINARY --lane REAL_DB --lane RECOVERY"
    )
    assert enforcement["env"] == {
        "BASH_ENV": "",
        "ENV": "",
        "SCOPE_RESULT": "${{ needs.scope.result }}",
        "POSTGRES_SCOPE": "${{ needs.scope.outputs.postgres }}",
        "ORDINARY_RESULT": "${{ needs.backend_postgres_ordinary.result }}",
        "REAL_DB_RESULT": "${{ needs.backend_postgres_real_db.result }}",
        "RECOVERY_RESULT": "${{ needs.backend_postgres_recovery.result }}",
        "EXPECTED_SHA": "${{ github.sha }}",
        "EXPECTED_SOURCE_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        "AGGREGATOR_SHA": "${{ steps.qualification.outputs.sha }}",
        "AGGREGATOR_SOURCE_SHA": "${{ steps.qualification.outputs.source_sha }}",
        "SCOPE_SHA": "${{ needs.scope.outputs.qualification_sha }}",
        "SCOPE_SOURCE_SHA": "${{ needs.scope.outputs.qualification_source_sha }}",
        "ORDINARY_SHA": "${{ needs.backend_postgres_ordinary.outputs.qualification_sha }}",
        "ORDINARY_SOURCE_SHA": "${{ needs.backend_postgres_ordinary.outputs.qualification_source_sha }}",
        "REAL_DB_SHA": "${{ needs.backend_postgres_real_db.outputs.qualification_sha }}",
        "REAL_DB_SOURCE_SHA": "${{ needs.backend_postgres_real_db.outputs.qualification_source_sha }}",
        "RECOVERY_SHA": "${{ needs.backend_postgres_recovery.outputs.qualification_sha }}",
        "RECOVERY_SOURCE_SHA": "${{ needs.backend_postgres_recovery.outputs.qualification_source_sha }}",
    }


def _assert_smoke_test_process_boundary() -> None:
    direct_entry_import = subprocess.run(
        [sys.executable, "-c", "import smoke_test"],
        cwd=_ROOT / "backend" / "scripts",
        check=False,
        capture_output=True,
        text=True,
    )
    assert direct_entry_import.returncode == 0, direct_entry_import.stderr
    smoke_parent = (_ROOT / "backend" / "scripts" / "smoke_test.py").read_text(
        encoding="utf-8"
    )
    smoke_child = (_ROOT / "backend" / "scripts" / "smoke_server.py").read_text(
        encoding="utf-8"
    )
    assert '"scripts.smoke_server"' in smoke_parent
    assert "dedicated_test_database_lease" not in smoke_parent
    assert smoke_child.index("with dedicated_test_database_lease(") < smoke_child.index(
        "uvicorn.run("
    )


def test_github_postgres_jobs_bind_scope_resources_commands_auth_and_sha() -> None:
    jobs = _workflow_jobs(_ROOT / ".github" / "workflows" / "ci.yml")
    scope = jobs["scope"]
    assert isinstance(scope, dict)
    assert scope["outputs"]["postgres_matrix"] == ("${{ steps.scope.outputs.postgres_matrix }}")
    assert scope["outputs"]["audit_base_sha"] == (
        "${{ steps.qualification.outputs.audit_base_sha }}"
    )
    _assert_bounded_timeout(scope)
    _assert_qualification_step(
        scope,
        _steps(scope)["Verify qualification SHA"],
        resolves_audit_base=True,
    )
    for name in ("backend_contracts", "backend_frozen", "windows_packaging"):
        job = jobs[name]
        assert job["outputs"]["qualification_sha"] == "${{ steps.qualification.outputs.sha }}"
        assert job["outputs"]["qualification_source_sha"] == ("${{ steps.qualification.outputs.source_sha }}")
        _assert_qualification_step(job, _steps(job)["Verify qualification SHA"])
    assert jobs["backend_contracts"]["needs"] == "scope"
    audit_environment = _steps(jobs["backend_contracts"])["Audit (release lanes)"]["env"]
    assert audit_environment["XPJ_AUDIT_BASE_REF"] == (
        "${{ needs.scope.outputs.audit_base_sha }}"
    )
    _assert_bounded_timeout(jobs["backend_contracts"])
    _assert_bounded_timeout(jobs["backend_frozen"])
    assert jobs["windows_packaging"]["timeout-minutes"] == 20

    assert jobs["backend_postgres_real_db"]["strategy"] == jobs[
        "backend_postgres_recovery"
    ]["strategy"]
    assert jobs["backend_postgres_ordinary"]["strategy"] != jobs[
        "backend_postgres_real_db"
    ]["strategy"]

    _assert_lane(
        jobs["backend_postgres_ordinary"],
        name=(
            "Backend PostgreSQL / ordinary ${{ matrix.shard.label }} "
            "(PG ${{ matrix.postgres['postgres-major'] }})"
        ),
        prepare_step="Prepare ordinary lane database",
        prepare_roles=("base",),
        runner_step="PostgreSQL parallel pytest lane",
        lane="ordinary",
        workers=4,
        shard_index="${{ matrix.shard.index }}",
        shard_count="${{ matrix.shard.count }}",
    )
    _assert_lane(
        jobs["backend_postgres_real_db"],
        name=(
            "Backend PostgreSQL / real-db "
            "(PG ${{ matrix.postgres['postgres-major'] }})"
        ),
        prepare_step="Prepare real-db lane database",
        prepare_roles=("base",),
        runner_step="PostgreSQL real-db serial pytest lane",
        lane="real-db",
        workers=1,
    )

    _assert_recovery_job(jobs["backend_postgres_recovery"])
    _assert_no_postgres_password_leaks(jobs)
    _assert_postgres_aggregator(jobs["backend-postgres"])
    _assert_smoke_test_process_boundary()


def test_gitea_keeps_the_shared_lane_runner_without_scope_modernization() -> None:
    workflow_path = _ROOT / ".gitea" / "workflows" / "windows-ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert "concurrency" not in workflow
    jobs = workflow["jobs"]
    assert "scope" not in jobs
    for job_id in ("backend-full", "backend-postgres", "desktop-manager", "android-unit"):
        job = jobs[job_id]
        assert "needs" not in job
        assert "if" not in job
    postgres = jobs["backend-postgres"]
    assert isinstance(postgres, dict)
    lane = next(step["run"] for step in postgres["steps"] if step["name"].startswith("PostgreSQL lane"))
    commands = [line.strip() for line in lane.splitlines() if _LANE_RUNNER in line]
    assert commands == [
        ".\\.ci-venv\\Scripts\\python.exe -m scripts.run_postgres_pytest_lane --lane ordinary --workers 1",
        ".\\.ci-venv\\Scripts\\python.exe -m scripts.run_postgres_pytest_lane --lane real-db --workers 1",
    ]
    assert "$ciPort = [int]$contract.ports.gitea" in lane
    assert "$null = Initialize-XpjTestPostgresRuntimeRoot" in lane
    assert "$datadir = Get-XpjTestPostgresDefaultDataDir -Port $ciPort" in lane
    assert "$datadir = Join-Path" not in lane
    assert ".\\scripts\\start_test_pg.ps1 -Port $ciPort -DataDir $datadir -AllowCiPort" in lane
    assert ".\\scripts\\stop_test_pg.ps1 -Port $ciPort -DataDir $datadir -AllowCiPort" in lane
    assert (
        "-m scripts.write_test_postgres_env --host localhost --port-profile gitea "
        "--admin-user postgres --existing-passfile $passfile --output $connectionEnv"
    ) in lane
    assert "$passfile = Join-Path $datadir ([string]$contract.passfile_name)" in lane
    assert "postgresql+psycopg://postgres@localhost:5433" not in lane
    assert "Remove-Item -Recurse" not in lane
    assert "initdb.exe" not in lane
    audit = load_ci_gap_audit()
    protected = audit._iter_workflow_run_commands([workflow_path.parent], protected_only=True)
    platform_missing = audit._missing_ci_invocations_by_platform(protected)
    assert not [item for item in platform_missing if item.startswith("Gitea: ")]
    path_scoped = audit._iter_workflow_run_commands([workflow_path.parent])
    gradle_missing = audit._missing_gradle_tasks_by_platform(protected, path_scoped_commands=path_scoped)
    assert not [item for item in gradle_missing if item.startswith("Gitea: ")]


def test_ci_gap_lane_matchers_accept_only_the_repository_runner_contract() -> None:
    mod = load_ci_gap_audit()
    ordinary = next(
        required for required in mod.REQUIRED_CI_INVOCATIONS if required.label == "pytest ordinary business lane"
    )
    real_db = next(
        required for required in mod.REQUIRED_CI_INVOCATIONS if required.label == "pytest real-db serial lane"
    )
    assert ordinary.matches("python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4")
    assert ordinary.matches("python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 1")
    assert ordinary.matches(
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 "
        "--shard-index 0 --shard-count 2"
    )
    assert ordinary.matches(
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 "
        '--shard-index "${{ matrix.shard.index }}" '
        '--shard-count "${{ matrix.shard.count }}"'
    )
    assert real_db.matches("python -m scripts.run_postgres_pytest_lane --lane real-db --workers 1")
    for command in (
        "python -m pytest tests -m real_db",
        "python scripts/run_postgres_pytest_lane.py --lane ordinary --workers 4",
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 --ignore tests/x.py",
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 5",
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 --shard-index 2 --shard-count 2",
        "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 --shard-index 0",
        (
            "python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 4 "
            '--shard-index "${{ matrix.shard.count }}" '
            '--shard-count "${{ matrix.shard.index }}"'
        ),
        "python -m scripts.run_postgres_pytest_lane --lane real-db --workers 1 --shard-index 0 --shard-count 2",
        "python -m scripts.run_postgres_pytest_lane --lane real-db --workers 2",
    ):
        assert not ordinary.matches(command)
        assert not real_db.matches(command)
