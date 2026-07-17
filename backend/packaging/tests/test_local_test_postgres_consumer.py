from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_runtime import (
    PROJECT_ROOT,
    TEST_POSTGRES_CONTRACT,
    _free_local_port,
    _run_lifecycle_contender,
    _windows_process_is_running,
)
from _powershell_contract import powershell_contract_engines

from scripts.test_pg_protected_file import ensure_protected_directory

pytestmark = pytest.mark.packaging_resource("postgres_cluster")


def _start_lifecycle_contender(
    engine: str,
    contender_script: Path,
    port: int,
    data_directory: Path,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(contender_script),
            "-Contract",
            str(TEST_POSTGRES_CONTRACT),
            "-Port",
            str(port),
            "-DataDirectory",
            str(data_directory),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_consumer_lease_and_smoke_child_parent_death_contract(tmp_path: Path) -> None:
    setup_authority_script = tmp_path / "setup-consumer-authority.ps1"
    setup_authority_script.write_text(
        "param($Contract,$DataDirectory,$Port,$SystemIdentifier)\n"
        ". $Contract\n"
        "[void][IO.Directory]::CreateDirectory($DataDirectory)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n"
        "$payload = [ordered]@{\n"
        "  schema_version = 3; kind = 'xiaopiaojia-test-postgres';\n"
        "  purpose = 'local'; port = [int]$Port; instance_id = ('b' * 32);\n"
        "  system_identifier = $SystemIdentifier; authentication = 'scram-sha-256'\n"
        "} | ConvertTo-Json -Compress\n"
        "Write-XpjTestPostgresProtectedUtf8File "
        "-Path (Join-Path $DataDirectory '.xpj-test-cluster.json') "
        "-Content ($payload + [Environment]::NewLine)\n"
        "Protect-XpjTestPostgresDirectoryTree $DataDirectory\n",
        encoding="ascii",
    )
    prepare_stale_script = tmp_path / "prepare-stale-consumer.ps1"
    prepare_stale_script.write_text(
        "param($Contract,$DataDirectory,$LeasePath)\n"
        ". $Contract\n"
        "$leaseDirectory = Get-XpjTestPostgresConsumerLeaseDirectory $DataDirectory\n"
        "[void][IO.Directory]::CreateDirectory($leaseDirectory)\n"
        "Protect-XpjTestPostgresDirectoryTree $leaseDirectory\n"
        "Write-XpjTestPostgresProtectedUtf8File -Path $LeasePath -Content '{'\n",
        encoding="ascii",
    )
    launcher_script = tmp_path / "launch-consumer.ps1"
    launcher_script.write_text(
        "param($Python, $ConsumerScript, $ChildPid)\n"
        "$quotedScript = '\"' + $ConsumerScript + '\"'\n"
        "$child = Start-Process -FilePath $Python -ArgumentList $quotedScript -PassThru\n"
        "[IO.File]::WriteAllText($ChildPid, [string]$child.Id)\n"
        "while ($true) { Start-Sleep -Seconds 1 }\n",
        encoding="ascii",
    )
    consumer_script = tmp_path / "hold-consumer.py"
    consumer_script.write_text(
        "import os, time\n"
        "from pathlib import Path\n"
        "from scripts.test_pg_contract import test_postgres_consumer_lease\n"
        "ready = Path(os.environ['XPJ_CONSUMER_READY'])\n"
        "release = Path(os.environ['XPJ_CONSUMER_RELEASE'])\n"
        "done = Path(os.environ['XPJ_CONSUMER_DONE'])\n"
        "with test_postgres_consumer_lease(os.environ['XPJ_CONSUMER_DATABASE_URL'], timeout_ms=5000):\n"
        "    ready.write_text('ready', encoding='ascii')\n"
        "    while not release.exists():\n"
        "        time.sleep(0.05)\n"
        "done.write_text('done', encoding='ascii')\n",
        encoding="ascii",
    )
    contender_script = tmp_path / "contend-lifecycle.ps1"
    contender_script.write_text(
        "param($Contract, $Port, $DataDirectory)\n"
        ". $Contract\n"
        "Invoke-XpjTestPostgresLifecycleLocked -Port $Port "
        "-DataDirectory $DataDirectory -TimeoutSeconds 1 -Operation {}\n",
        encoding="ascii",
    )
    atomic_handoff_script = tmp_path / "hold-atomic-handoff.ps1"
    atomic_handoff_script.write_text(
        "param($Contract, $Port, $DataDirectory, $InstanceId, "
        "$SystemIdentifier, $Ready, $Release)\n"
        ". $Contract\n"
        "$lease = Invoke-XpjTestPostgresLifecycleLocked -Port $Port "
        "-DataDirectory $DataDirectory "
        "-TimeoutSeconds 5 -Operation {\n"
        "  Enter-XpjTestPostgresConsumerLease -Port $Port "
        "-DataDirectory $DataDirectory -InstanceId $InstanceId "
        "-SystemIdentifier $SystemIdentifier "
        "-TimeoutSeconds 5\n"
        "}\n"
        "if ($null -eq $lease -or $null -eq $lease.Stream) { "
        "throw 'atomic handoff did not return one live lease' }\n"
        "try {\n"
        "  [IO.File]::WriteAllText($Ready, 'ready')\n"
        "  while (-not (Test-Path -LiteralPath $Release)) { "
        "Start-Sleep -Milliseconds 50 }\n"
        "}\n"
        "finally { Exit-XpjTestPostgresConsumerLease $lease }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        port = _free_local_port()
        data_directory = tmp_path / f"consumer-cluster-{index}"
        instance_id = "b" * 32
        system_identifier = f"12345678901234567{index + 10}"
        prepared = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(setup_authority_script),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-DataDirectory",
                str(data_directory),
                "-Port",
                str(port),
                "-SystemIdentifier",
                system_identifier,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        child_pid_path = tmp_path / f"child-{index}.pid"
        consumer_ready = tmp_path / f"consumer-{index}.ready"
        consumer_release = tmp_path / f"consumer-{index}.release"
        consumer_done = tmp_path / f"consumer-{index}.done"
        environment = os.environ.copy() | {
            "XPJ_CONSUMER_DATABASE_URL": (f"postgresql+psycopg://postgres@127.0.0.1:{port}/xpj_test"),
            "XPJ_CONSUMER_READY": str(consumer_ready),
            "XPJ_CONSUMER_RELEASE": str(consumer_release),
            "XPJ_CONSUMER_DONE": str(consumer_done),
            "XPJ_TEST_CLUSTER_AUTHORITY": "owned-marker",
            "XPJ_TEST_CLUSTER_INSTANCE_ID": instance_id,
            "XPJ_TEST_CLUSTER_MARKER_PATH": str(data_directory / ".xpj-test-cluster.json"),
            "XPJ_TEST_CLUSTER_SYSTEM_IDENTIFIER": system_identifier,
        }
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(PROJECT_ROOT / "backend"), existing_pythonpath) if part
        )
        launcher = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(launcher_script),
                "-Python",
                sys.executable,
                "-ConsumerScript",
                str(consumer_script),
                "-ChildPid",
                str(child_pid_path),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        child_pid: int | None = None
        try:
            deadline = time.monotonic() + 10
            while not consumer_ready.exists() and time.monotonic() < deadline:
                assert launcher.poll() is None, launcher.communicate(timeout=2)[0]
                time.sleep(0.05)
            assert consumer_ready.exists()
            child_pid = int(child_pid_path.read_text(encoding="ascii"))
            lease_directory = data_directory / ".xpj-test-postgres-consumers"
            assert len(list(lease_directory.glob("*.lease"))) == 1
            assert not list(lease_directory.glob("*.lease.json"))
            assert not list(lease_directory.glob("*.lease.lock"))

            launcher.kill()
            launcher.communicate(timeout=10)
            blocked = _run_lifecycle_contender(
                engine,
                contender_script,
                port,
                data_directory,
            )
            assert blocked.returncode != 0
            assert "Timed out waiting for 1 test PostgreSQL consumer lease" in (blocked.stdout + blocked.stderr)

            waiting = _start_lifecycle_contender(
                engine,
                contender_script,
                port,
                data_directory,
            )
            time.sleep(0.2)
            assert waiting.poll() is None
            consumer_release.write_text("release", encoding="ascii")
            waiting_output = waiting.communicate(timeout=10)[0]
            assert waiting.returncode == 0, waiting_output
            deadline = time.monotonic() + 10
            while not consumer_done.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert consumer_done.exists()
            child_pid = None

            untrusted_stale = lease_directory / ("1-00000000000000000000000000000000.lease")
            ensure_protected_directory(
                lease_directory,
                label="Test PostgreSQL consumer lease directory",
            )
            untrusted_stale.write_text("{", encoding="utf-8")
            untrusted_cleanup = _run_lifecycle_contender(
                engine,
                contender_script,
                port,
                data_directory,
            )
            assert untrusted_cleanup.returncode != 0
            assert "lease ACL is invalid" in (untrusted_cleanup.stdout + untrusted_cleanup.stderr)
            untrusted_stale.unlink()

            stale_lease = lease_directory / ("1-00000000000000000000000000000000.lease")
            prepared_stale = subprocess.run(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(prepare_stale_script),
                    "-Contract",
                    str(TEST_POSTGRES_CONTRACT),
                    "-DataDirectory",
                    str(data_directory),
                    "-LeasePath",
                    str(stale_lease),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            assert prepared_stale.returncode == 0, prepared_stale.stdout + prepared_stale.stderr
            stale_cleanup = _run_lifecycle_contender(
                engine,
                contender_script,
                port,
                data_directory,
            )
            assert stale_cleanup.returncode == 0, stale_cleanup.stdout + stale_cleanup.stderr
            assert not stale_lease.exists()
            assert not lease_directory.exists()

            handoff_ready = tmp_path / f"handoff-{index}.ready"
            handoff_release = tmp_path / f"handoff-{index}.release"
            handoff = subprocess.Popen(
                [
                    engine,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(atomic_handoff_script),
                    "-Contract",
                    str(TEST_POSTGRES_CONTRACT),
                    "-Port",
                    str(port),
                    "-DataDirectory",
                    str(data_directory),
                    "-InstanceId",
                    instance_id,
                    "-SystemIdentifier",
                    system_identifier,
                    "-Ready",
                    str(handoff_ready),
                    "-Release",
                    str(handoff_release),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                deadline = time.monotonic() + 10
                while not handoff_ready.exists() and time.monotonic() < deadline:
                    assert handoff.poll() is None, handoff.communicate(timeout=2)[0]
                    time.sleep(0.05)
                assert handoff_ready.exists()
                handoff_blocked = _run_lifecycle_contender(
                    engine,
                    contender_script,
                    port,
                    data_directory,
                )
                assert handoff_blocked.returncode != 0
                assert "consumer lease" in (handoff_blocked.stdout + handoff_blocked.stderr)
            finally:
                handoff_release.write_text("release", encoding="ascii")
                handoff_output, _ = handoff.communicate(timeout=10)
            assert handoff.returncode == 0, handoff_output
            handoff_unblocked = _run_lifecycle_contender(
                engine,
                contender_script,
                port,
                data_directory,
            )
            assert handoff_unblocked.returncode == 0, handoff_unblocked.stdout + handoff_unblocked.stderr
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.communicate(timeout=10)
            if child_pid is not None:
                consumer_release.write_text("release", encoding="ascii")
                with contextlib.suppress(OSError):
                    os.kill(child_pid, 15)

    smoke_child = tmp_path / "smoke-watch-child.py"
    smoke_child.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from scripts.smoke_test import start_smoke_parent_watchdog\n"
        "parent_pid, parent_created, ready = sys.argv[1:]\n"
        "start_smoke_parent_watchdog(parent_process_id=int(parent_pid), "
        "parent_created=int(parent_created))\n"
        "Path(ready).write_text('ready', encoding='ascii')\n"
        "while True:\n"
        "    time.sleep(1)\n",
        encoding="ascii",
    )
    smoke_parent = tmp_path / "smoke-watch-parent.py"
    smoke_parent.write_text(
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "from scripts.smoke_test import windows_process_creation_identity\n"
        "child, child_pid_path, ready = sys.argv[1:]\n"
        "process = subprocess.Popen([sys.executable, child, str(os.getpid()), "
        "str(windows_process_creation_identity(os.getpid())), ready])\n"
        "Path(child_pid_path).write_text(str(process.pid), encoding='ascii')\n"
        "while True:\n"
        "    time.sleep(1)\n",
        encoding="ascii",
    )
    smoke_child_pid = tmp_path / "smoke-watch-child.pid"
    smoke_ready = tmp_path / "smoke-watch.ready"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(PROJECT_ROOT / "backend"),
            environment.get("PYTHONPATH", ""),
        )
        if part
    )
    parent = subprocess.Popen(
        [
            sys.executable,
            str(smoke_parent),
            str(smoke_child),
            str(smoke_child_pid),
            str(smoke_ready),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    child_process_id: int | None = None
    try:
        deadline = time.monotonic() + 10
        while not smoke_ready.exists() and time.monotonic() < deadline:
            assert parent.poll() is None, parent.communicate(timeout=2)[0]
            time.sleep(0.05)
        assert smoke_ready.exists()
        child_process_id = int(smoke_child_pid.read_text(encoding="ascii"))
        parent.kill()
        parent.communicate(timeout=10)

        deadline = time.monotonic() + 10
        while _windows_process_is_running(child_process_id) and time.monotonic() < deadline:
            time.sleep(0.05)
        if not _windows_process_is_running(child_process_id):
            child_process_id = None
        assert child_process_id is None, "smoke child survived its exact parent generation"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate(timeout=10)
        if child_process_id is not None:
            with contextlib.suppress(OSError):
                os.kill(child_process_id, 15)
