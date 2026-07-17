from __future__ import annotations

import json
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
    _open_exact_windows_process,
    _run_lifecycle_contender,
    _terminate_exact_windows_process,
    _windows_process_handle_is_running,
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
        "$payload = @{ pid = $child.Id; "
        "created = $child.StartTime.ToUniversalTime().ToFileTimeUtc() } "
        "| ConvertTo-Json -Compress\n"
        "$temporary = $ChildPid + '.' + $PID + '.tmp'\n"
        "[IO.File]::WriteAllText($temporary, $payload, [Text.Encoding]::ASCII)\n"
        "[IO.File]::Move($temporary, $ChildPid)\n"
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
    idempotent_close_script = tmp_path / "verify-idempotent-consumer-close.ps1"
    idempotent_close_script.write_text(
        "param($Contract, $LeasePath)\n"
        ". $Contract\n"
        "$events = [System.Collections.Generic.List[string]]::new()\n"
        "$stream = [pscustomobject]@{ Events = $events }\n"
        "$stream | Add-Member ScriptMethod Unlock { "
        "param($Offset, $Length) [void]$this.Events.Add('unlock'); "
        "throw 'synthetic unlock failure' }\n"
        "$stream | Add-Member ScriptMethod Dispose { "
        "[void]$this.Events.Add('stream-dispose') }\n"
        "$directoryLease = [pscustomobject]@{ Events = $events; Name = 'directory-dispose' }\n"
        "$directoryLease | Add-Member ScriptMethod Dispose { "
        "[void]$this.Events.Add($this.Name) }\n"
        "$dataLease = [pscustomobject]@{ Events = $events; Name = 'data-dispose' }\n"
        "$dataLease | Add-Member ScriptMethod Dispose { "
        "[void]$this.Events.Add($this.Name) }\n"
        "[IO.File]::WriteAllText($LeasePath, 'lease')\n"
        "$lease = [pscustomobject]@{ Path = $LeasePath; Stream = $stream; "
        "LockOffset = [int64]1073741824; DataPathLease = $dataLease; "
        "LeaseDirectoryPathLease = $directoryLease }\n"
        "$firstFailed = $false\n"
        "try { Exit-XpjTestPostgresConsumerLease $lease } "
        "catch { $firstFailed = $_.Exception.ToString().Contains('synthetic unlock failure') }\n"
        "if (-not $firstFailed) { throw 'first close did not preserve its cleanup failure' }\n"
        "if (Test-Path -LiteralPath $LeasePath) { throw 'lease file survived failed close' }\n"
        "if ($null -ne $lease.Stream -or $null -ne $lease.Path -or "
        "$null -ne $lease.DataPathLease -or $null -ne $lease.LeaseDirectoryPathLease) { "
        "throw 'close retained transferred ownership' }\n"
        "Exit-XpjTestPostgresConsumerLease $lease\n"
        "$expected = 'unlock,stream-dispose,directory-dispose,data-dispose'\n"
        "if (($events -join ',') -cne $expected) { "
        "throw ('cleanup was repeated or incomplete: ' + ($events -join ',')) }\n",
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
        close_contract = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(idempotent_close_script),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-LeasePath",
                str(tmp_path / f"idempotent-close-{index}.lease"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert close_contract.returncode == 0, close_contract.stdout + close_contract.stderr
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
        child_kernel32: object | None = None
        child_handle: object | None = None
        try:
            deadline = time.monotonic() + 10
            while not consumer_ready.exists() and time.monotonic() < deadline:
                assert launcher.poll() is None, launcher.communicate(timeout=2)[0]
                time.sleep(0.05)
            assert consumer_ready.exists()
            child_identity = json.loads(child_pid_path.read_text(encoding="ascii"))
            child_kernel32, child_handle = _open_exact_windows_process(
                int(child_identity["pid"]),
                int(child_identity["created"]),
            )
            assert _windows_process_handle_is_running(child_kernel32, child_handle)
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
            assert child_kernel32.WaitForSingleObject(child_handle, 10_000) == 0
            child_kernel32.CloseHandle(child_handle)
            child_kernel32 = None
            child_handle = None

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
            if child_kernel32 is not None and child_handle is not None:
                consumer_release.write_text("release", encoding="ascii")
                _terminate_exact_windows_process(child_kernel32, child_handle)
                child_kernel32.CloseHandle(child_handle)

    smoke_child = tmp_path / "smoke-watch-child.py"
    smoke_child.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "from scripts.smoke_test import start_smoke_parent_watchdog\n"
        "from scripts.test_pg_windows_contract import (\n"
        "    _windows_process_created_filetime, _windows_process_kernel32,\n"
        ")\n"
        "parent_pid, parent_created, ready = sys.argv[1:]\n"
        "start_smoke_parent_watchdog(parent_process_id=int(parent_pid), "
        "parent_created=int(parent_created))\n"
        "kernel32 = _windows_process_kernel32()\n"
        "created = _windows_process_created_filetime(kernel32, kernel32.GetCurrentProcess())\n"
        "payload = json.dumps({'pid': os.getpid(), 'created': created})\n"
        "ready_path = Path(ready)\n"
        "temporary = ready_path.with_name(f'.{ready_path.name}.{os.getpid()}.tmp')\n"
        "temporary.write_text(payload, encoding='ascii')\n"
        "temporary.replace(ready_path)\n"
        "while True:\n"
        "    time.sleep(1)\n",
        encoding="ascii",
    )
    smoke_parent = tmp_path / "smoke-watch-parent.py"
    smoke_parent.write_text(
        "import os, subprocess, sys, time\n"
        "from scripts.smoke_test import windows_process_creation_identity\n"
        "child, ready = sys.argv[1:]\n"
        "process = subprocess.Popen([sys.executable, child, str(os.getpid()), "
        "str(windows_process_creation_identity(os.getpid())), ready])\n"
        "while True:\n"
        "    time.sleep(1)\n",
        encoding="ascii",
    )
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
            str(smoke_ready),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    smoke_kernel32: object | None = None
    smoke_child_handle: object | None = None
    try:
        deadline = time.monotonic() + 10
        while not smoke_ready.exists() and time.monotonic() < deadline:
            assert parent.poll() is None, parent.communicate(timeout=2)[0]
            time.sleep(0.05)
        assert smoke_ready.exists()
        smoke_identity = json.loads(smoke_ready.read_text(encoding="ascii"))
        smoke_kernel32, smoke_child_handle = _open_exact_windows_process(
            int(smoke_identity["pid"]),
            int(smoke_identity["created"]),
        )
        assert _windows_process_handle_is_running(smoke_kernel32, smoke_child_handle)
        parent.kill()
        parent.communicate(timeout=10)
        assert smoke_kernel32.WaitForSingleObject(smoke_child_handle, 10_000) == 0
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate(timeout=10)
        if smoke_kernel32 is not None and smoke_child_handle is not None:
            _terminate_exact_windows_process(smoke_kernel32, smoke_child_handle)
            smoke_kernel32.CloseHandle(smoke_child_handle)
