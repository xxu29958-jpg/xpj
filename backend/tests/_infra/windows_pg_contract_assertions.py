"""Static source and workflow contracts for disposable Windows PostgreSQL."""

from __future__ import annotations

import re
from pathlib import Path


def _assert_postgres_binary_discovery(project_root: Path) -> None:
    script_paths = (
        project_root / "backend/scripts/test_pg_data_directory_contract.ps1",
        project_root / "backend/scripts/backup_database.ps1",
        project_root / "backend/packaging/install_ticketbox.ps1",
    )
    for script_path in script_paths:
        script = script_path.read_text(encoding="utf-8-sig")
        assert "SpecialFolder]::ProgramFiles" in script
        assert 'GetEnvironmentVariable("ProgramFiles", "Machine")' not in script
        assert r"C:\Program Files\PostgreSQL" not in script


def _assert_postgres_process_contract(contracts: dict[str, str]) -> None:
    start = contracts["start"]
    stop = contracts["stop"]
    cluster = contracts["cluster"]
    staging = contracts["staging"]
    deletion = contracts["deletion"]
    process = contracts["process"]
    job = contracts["job"]
    assert "test_pg_cluster_contract.ps1" in start
    assert "test_pg_cluster_contract.ps1" in stop
    assert "OwningProcess" in cluster
    assert "listen_addresses=127.0.0.1" in start
    assert "pg_controldata.exe" in cluster
    assert "pg_control_system()" in cluster
    assert "XPJ_TEST_POSTGRES_IDENTITY_MISMATCH" in cluster
    assert ".xpj-init-" in cluster
    assert "$stagingHandle.RenameTo($DataDirectory)" in cluster
    assert "Get-XpjTestPostgresProcessGeneration" in cluster
    assert "Enter-XpjTestPostgresLifecycleMutex" in cluster
    assert "Enter-XpjTestPostgresConsumerLease" in cluster
    assert "Wait-XpjTestPostgresConsumersDrained" in cluster
    assert "-InstanceId $marker.InstanceId" in start
    assert "InstanceId = $InstanceId" in cluster
    assert "[string]$payload.InstanceId -cne $InstanceId" in cluster
    assert "Protect-XpjTestPostgresDirectoryTree" in cluster
    assert "Get-XpjTestPostgresCurrentUserSid" in cluster
    assert "[XpjTestDirectoryPathLease]::OpenPath($DataDir)" in start
    assert "Invoke-XpjTestPostgresLifecycleLocked" in start
    assert "Invoke-XpjTestPostgresLifecycleLocked" in stop
    assert "OwnerStartedAtUtc" in staging
    assert "Remove-XpjTestPostgresAbandonedStaging" in staging
    assert "Assert-XpjTestPostgresProtectedAuthorityFile" in staging
    assert "PostgreSQL staging receipt" in staging
    assert "Remove-XpjTestPostgresDirectoryBounded" in staging
    assert "New-XpjTestPostgresDeletionReceipt" in stop
    assert "Complete-XpjTestPostgresPendingDeletion" in start
    assert "Complete-XpjTestPostgresPendingDeletion" in stop
    assert "instance_id = $InstanceId" in cluster
    assert "DirectoryIdentity" in staging
    assert "InstanceId" in deletion
    assert "Assert-XpjTestPostgresDeletionDirectoryInstance" in deletion
    assert "Assert-XpjTestPostgresProtectedAuthorityFile" in deletion
    assert "Test PostgreSQL deletion receipt" in deletion
    assert "[XpjTestDirectoryMoveHandle]::OpenIdentity($DataDirectory)" in deletion
    assert "$directoryMove.RenameTo($tombstone)" in deletion
    assert "ExpectedDirectoryIdentity" in deletion
    assert "Assert-XpjTestPostgresQuiescent" in deletion[
        deletion.index("if (Test-Path -LiteralPath $tombstone)") :
    ]
    assert "Invoke-XpjTestPostgresBoundedProcess" in cluster
    assert "WaitForStartedProcess($TimeoutSeconds * 1000)" in process
    assert "XpjTestProcessJob" in process
    assert "TerminateJobObject" in job
    assert "JobObjectLimitKillOnJobClose" in job
    assert "Start-XpjTestPostgresUncommittedProcess" in process
    assert "Remove-XpjTestPostgresProcessOutput" in process
    assert "[System.IO.FileShare]::None" in process
    assert "process output handle did not close" in process
    assert "PreserveProcessesOnClose" in process
    assert "ProcThreadAttributeJobList" in job
    assert "ProcThreadAttributeHandleList" in job
    assert "ContainsStartedProcess" in process
    assert "IsStartedProcessRunning" in process
    assert "Stop-Process -Id $targetProcessId" not in process
    assert "Get-Process -Id ([int]$Transaction.TargetProcessId)" not in process
    assert "CreateProcess" in job
    assert "Get-CimInstance -ClassName Win32_Process" not in staging
    assert "statement_timeout=$statementTimeoutMs" in cluster
    assert "XPJ_TEST_POSTGRES_ACTIVE_CONSUMERS" in cluster
    assert "FileShareDelete" not in job
    assert "WaitForAllProcesses" in job
    assert "ActiveProcesses" in job
    assert "Assert-XpjTestPostgresQuiescent" in stop
    assert "Assert-XpjTestPostgresCleanShutdown" in cluster
    assert "[void]$verifiedProcess.Handle" in stop
    assert "Stop-XpjTestPostgresVerifiedPostmaster" in stop
    assert "@('kill', 'INT', [string]$ProcessId)" in cluster
    assert "pg_ctl.exe" in cluster
    assert "taskkill" not in (start + stop + cluster).lower()


def _assert_authentication_contract(contracts: dict[str, str]) -> None:
    start = contracts["start"]
    stop = contracts["stop"]
    cluster = contracts["cluster"]
    authentication = contracts["authentication"]
    assert "--auth-host=scram-sha-256" in cluster
    assert "--auth-local=scram-sha-256" in cluster
    assert "--auth=trust" not in cluster
    assert "Prepare-XpjTestPostgresScramAuthenticationOffline" in authentication
    assert "Assert-XpjTestPostgresScramAuthenticationOnline" in authentication
    assert "scram-sha-256" in authentication
    assert "PGPASSWORD" not in authentication
    assert "PGPASSFILE" in authentication
    assert "PGREQUIREAUTH" in authentication
    assert "Assert-XpjTestPostgresRequiredAuthClient" in authentication
    assert "ProductMajorPart" in authentication
    assert "postgres.exe" in authentication
    assert "'--single'" in authentication
    assert "Assert-XpjTestPostgresLegacyOnlineIdentity" in authentication
    assert "-RequiredAuthentication 'none'" in authentication
    assert "Invoke-XpjTestPostgresIsolatedLibpqEnvironment" in authentication
    assert "StandardInput" in authentication
    assert "XPJ_TEST_POSTGRES_CREDENTIAL_FILE" in start
    assert "Assert-XpjTestPostgresRequiredAuthClient" in start
    assert "Assert-XpjTestPostgresRequiredAuthClient" in stop
    assert "XPJ_TEST_POSTGRES_PASSWORD" not in start
    assert "postgres:$databasePassword@" not in start


def _assert_protected_file_contract(contracts: dict[str, str]) -> None:
    cluster = contracts["cluster"]
    protected_file = contracts["protected_file"]
    protected_python = contracts["protected_python"]
    python_consumer = contracts["python_consumer"]
    assert "test_pg_protected_file.cs" in cluster
    assert "CreateFileW" in protected_file
    assert "FileShare.None" in protected_file
    assert "FileShare.Read" in protected_file
    assert "FileShare.ReadWrite" in protected_file
    assert "D:P(A;;FA;;;" in protected_file
    assert "CreateNewDisposition" in protected_file
    assert "FileFlagWriteThrough" in protected_file
    assert "InheritHandle = inheritHandle ? 1 : 0" in protected_file
    assert "CreateNewInheritableProcessOutput" in protected_file
    assert "CreateNewSharedLock" in protected_file
    assert "CreateFileW" in protected_python
    assert "_FILE_FLAG_OPEN_REPARSE_POINT" in protected_python
    assert "_CREATE_NEW = 1" in protected_python
    assert "_FILE_FLAG_WRITE_THROUGH" in protected_python
    assert "GetNamedSecurityInfoW" in protected_python
    assert "_protected_sddl" in protected_python
    assert 'f"(A;{inheritance};FA;;;{sid})"' in protected_python
    assert "_assert_no_reparse_ancestors(path.parent)" in protected_python
    assert "assert_protected_authority_file" in protected_python
    assert "read_protected_utf8_file" in protected_python
    assert "TEST_CLUSTER_INSTANCE_ID_ENV" in python_consumer
    assert "instance_id != expected_instance_id" in python_consumer
    assert "write_protected_utf8_file" in python_consumer
    assert "os.open(" not in python_consumer


def _assert_script_contract(project_root: Path) -> None:
    scripts = project_root / "backend" / "scripts"
    cluster_modules = (
        "test_pg_cluster_contract.ps1",
        "test_pg_lifecycle_lock_contract.ps1",
        "test_pg_acl_contract.ps1",
        "test_pg_consumer_lease_contract.ps1",
        "test_pg_data_directory_contract.ps1",
        "test_pg_runtime_identity_contract.ps1",
        "test_pg_auth_contract.ps1",
    )
    authentication_modules = (
        "test_pg_auth_contract.ps1",
        "test_pg_psql_command_contract.ps1",
    )
    contracts = {
        "start": (scripts / "start_test_pg.ps1").read_text(encoding="utf-8-sig"),
        "stop": (scripts / "stop_test_pg.ps1").read_text(encoding="utf-8-sig"),
        "cluster": "\n".join((scripts / name).read_text(encoding="utf-8-sig") for name in cluster_modules),
        "staging": (scripts / "test_pg_staging_contract.ps1").read_text(encoding="utf-8-sig"),
        "deletion": (scripts / "test_pg_deletion_contract.ps1").read_text(encoding="utf-8-sig"),
        "process": (scripts / "test_pg_process_contract.ps1").read_text(encoding="utf-8-sig"),
        "job": "\n".join(
            (scripts / name).read_text(encoding="utf-8")
            for name in (
                "test_pg_process_job.cs",
                "test_pg_process_command_line.cs",
                "test_pg_process_native.cs",
            )
        ),
        "protected_file": (scripts / "test_pg_protected_file.cs").read_text(
            encoding="utf-8"
        ),
        "protected_python": "\n".join(
            (scripts / name).read_text(encoding="utf-8")
            for name in (
                "test_pg_protected_file.py",
                "test_pg_protected_reader.py",
            )
        ),
        "python_consumer": "\n".join(
            (scripts / name).read_text(encoding="utf-8")
            for name in (
                "test_pg_authority_contract.py",
                "test_pg_contract.py",
            )
        ),
        "authentication": "\n".join(
            (scripts / name).read_text(encoding="utf-8-sig")
            for name in authentication_modules
        ),
    }
    cluster_entrypoint = (scripts / "test_pg_cluster_contract.ps1").read_text(encoding="utf-8-sig")
    for name in cluster_modules[1:]:
        assert name in cluster_entrypoint
    assert authentication_modules[1] in (scripts / authentication_modules[0]).read_text(
        encoding="utf-8-sig"
    )
    _assert_postgres_binary_discovery(project_root)
    _assert_postgres_process_contract(contracts)
    _assert_authentication_contract(contracts)
    _assert_protected_file_contract(contracts)


def _assert_packaging_runtime_budget(
    workflow: str,
    *,
    job_name: str,
    next_job_name: str,
    job_minutes: int,
) -> None:
    job = workflow.split(f"  {job_name}:", 1)[1].split(f"\n  {next_job_name}:", 1)[0]
    assert f"    timeout-minutes: {job_minutes}" in job
    step = job.split("      - name: Windows installer safety behavior\n", 1)[1].split("\n      - name:", 1)[0]
    assert "        timeout-minutes: 10" in step
    assert '          XPJ_REQUIRE_WINDOWS_LIFECYCLE_RUNTIME: "1"' in step
    assert "scripts/run_packaging_tests.py" in step.replace("\\", "/")


def _assert_required_windows_runtime(project_root: Path) -> None:
    packaging_tests = project_root / "backend/packaging/tests"
    lifecycle_test = (packaging_tests / "_local_test_postgres_runtime.py").read_text(encoding="utf-8") + "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(packaging_tests.glob("test_local_test_postgres_*.py"))
    )
    lifecycle_conftest = (project_root / "backend/packaging/tests/conftest.py").read_text(encoding="utf-8")
    assert '"postgres.exe"' in lifecycle_test
    assert "pytest.fail(message)" in lifecycle_test
    assert "strict packaging contracts skipped" in lifecycle_conftest


def _step_timeout(job: str, name: str) -> int:
    match = re.search(
        rf"^      - name: {re.escape(name)}\n        timeout-minutes:\s*(\d+)$",
        job,
        re.MULTILINE,
    )
    assert match is not None, f"missing timeout for {name}"
    return int(match.group(1))


def _assert_gitea_postgres_job_budget(gitea_ci: str) -> None:
    job = gitea_ci.split("  backend-postgres:", 1)[1].split("\n  desktop-manager:", 1)[0]
    timeout_match = re.search(r"^    timeout-minutes:\s*(\d+)$", job, re.MULTILINE)
    assert timeout_match is not None
    execution_ceiling = sum(
        _step_timeout(job, name)
        for name in (
            "Checkout (offline — local Gitea, no github.com)",
            "Verify Gitea runner lifecycle contract",
            "Install backend dependencies",
            "PostgreSQL lane — ephemeral cluster + smoke + suite",
        )
    )
    cleanup_ceiling = _step_timeout(job, "Stop ephemeral PostgreSQL (backstop)")
    cleanup_step = re.search(
        r"^      - name: Stop ephemeral PostgreSQL \(backstop\)\n"
        r"(?P<body>(?:        .*\n)+)",
        job,
        re.MULTILINE,
    )
    assert cleanup_step is not None
    assert re.search(
        r"^        if:\s*always\(\)\s*$",
        cleanup_step.group("body"),
        re.MULTILINE,
    )
    assert execution_ceiling + cleanup_ceiling < int(timeout_match.group(1))


def _assert_workflow_contract(project_root: Path) -> None:
    gitea_ci = (project_root / ".gitea/workflows/windows-ci.yml").read_text(encoding="utf-8")
    github_ci = (project_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _assert_packaging_runtime_budget(
        github_ci,
        job_name="backend",
        next_job_name="backend-postgres",
        job_minutes=60,
    )
    _assert_packaging_runtime_budget(
        gitea_ci,
        job_name="backend-full",
        next_job_name="backend-postgres",
        job_minutes=70,
    )
    _assert_required_windows_runtime(project_root)
    assert gitea_ci.count(r".\scripts\start_test_pg.ps1 -Purpose ci") == 1
    assert gitea_ci.count(r".\scripts\stop_test_pg.ps1 -Purpose ci") == 2
    assert 'Join-Path $env:TEMP "xpj_pg_ci_$pgport"' in gitea_ci
    assert "GITHUB_RUN_ATTEMPT" not in gitea_ci
    assert "-ResetDatabases" in gitea_ci
    assert gitea_ci.count("AcquireConsumerLease") == 1
    assert "Enter-XpjTestPostgresConsumerLease" not in gitea_ci
    assert gitea_ci.count("Exit-XpjTestPostgresConsumerLease") == 2
    assert gitea_ci.count("assert_gitea_runner_contract.ps1") == 3
    assert "XPJ_TEST_PG_LIFECYCLE_MUTEX_OWNER_PID" not in gitea_ci
    assert "concurrency:" not in gitea_ci
    assert "taskkill" not in gitea_ci.lower()
    assert "createdb.exe" not in gitea_ci
    assert "Remove-Item -Recurse -Force $datadir" not in gitea_ci
    assert "XPJ_TEST_CLUSTER_INSTANCE_ID" in github_ci
    _assert_gitea_postgres_job_budget(gitea_ci)
    connected_ci = (project_root / ".gitea/workflows/android-connected.yml").read_text(encoding="utf-8")
    assert connected_ci.count("assert_gitea_runner_contract.ps1") == 1
    verify_project = (project_root / "scripts/verify_project.ps1").read_text(encoding="utf-8-sig")
    packaging_tests = verify_project.index("scripts/run_packaging_tests.py")
    database_reset = verify_project.index("start_test_pg.ps1")
    lease_start = verify_project.index("-AcquireConsumerLease", database_reset)
    final_consumer = verify_project.index("smoke_test.py")
    lease_end = verify_project.index("Exit-XpjTestPostgresConsumerLease")
    assert "packaging/tests" in verify_project
    assert packaging_tests < database_reset < lease_start < final_consumer < lease_end


def assert_windows_test_postgres_contract(project_root: Path) -> None:
    _assert_script_contract(project_root)
    _assert_workflow_contract(project_root)
