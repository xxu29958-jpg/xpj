from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from _local_test_postgres_recovery_probes import (
    write_abandoned_staging_probe,
    write_live_tombstone_probes,
    write_post_initdb_fault_probe,
)
from _local_test_postgres_runtime import (
    START_TEST_POSTGRES,
    TEST_POSTGRES_CONTRACT,
    _free_local_port,
    _postgres_bin,
    _run_lifecycle,
    _stop_preserving_data,
)
from _powershell_contract import powershell_contract_engines

pytestmark = pytest.mark.packaging_resource("postgres_cluster")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_abandoned_staging_requires_a_verified_receipt(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    final_dir = tmp_path / "owned-final"
    owned_staging = tmp_path / ".owned-final.xpj-init-owned"
    unowned_staging = tmp_path / ".owned-final.xpj-init-unowned"
    probe = tmp_path / "cleanup-staging.ps1"
    write_abandoned_staging_probe(probe)

    for engine in powershell_contract_engines():
        result = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-FinalDir",
                str(final_dir),
                "-Owned",
                str(owned_staging),
                "-Unowned",
                str(unowned_staging),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        unowned_staging.rmdir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_post_initdb_fault_cleans_current_process_staging(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    probe = tmp_path / "fault-after-initdb.ps1"
    write_post_initdb_fault_probe(probe)
    for index, engine in enumerate(powershell_contract_engines()):
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-FinalDir",
                str(tmp_path / f"faulted-{index}"),
                "-Port",
                str(_free_local_port()),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_interrupted_deletion_receipt_resumes_exact_target(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    prepare = tmp_path / "prepare-delete.ps1"
    prepare.write_text(
        "param($Contract, $PostgresBin, $DataDir, $Port, $TombstonePath)\n"
        ". $Contract\n"
        "$marker = Assert-XpjTestPostgresDataOwnership -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "New-XpjTestPostgresDeletionReceipt -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port "
        "-SystemIdentifier $marker.SystemIdentifier | Out-Null\n"
        "$receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDir\n"
        "$receipt = Read-XpjTestPostgresDeletionReceipt -ReceiptPath $receiptPath "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "[IO.File]::WriteAllText($TombstonePath, [string]$receipt.TombstoneDirectory)\n",
        encoding="ascii",
    )
    hold_move = tmp_path / "hold-directory-move.ps1"
    hold_move.write_text(
        "param($Contract, $DataDir, $Tombstone, $Ready, $Release)\n"
        ". $Contract\n"
        "$move = [XpjTestDirectoryMoveHandle]::Open($DataDir)\n"
        "try {\n"
        "  [IO.File]::WriteAllText($Ready, 'ready')\n"
        "  while (-not (Test-Path -LiteralPath $Release)) { "
        "Start-Sleep -Milliseconds 50 }\n"
        "  $move.RenameTo($Tombstone)\n"
        "}\n"
        "finally { $move.Dispose() }\n",
        encoding="ascii",
    )
    resume = tmp_path / "resume-delete.ps1"
    resume.write_text(
        "param($Contract, $PostgresBin, $DataDir, $Port)\n"
        ". $Contract\n"
        "New-Item -ItemType Directory -Path $DataDir | Out-Null\n"
        "$sentinel = Join-Path $DataDir 'new-owner.txt'\n"
        "[IO.File]::WriteAllText($sentinel, 'keep')\n"
        "Complete-XpjTestPostgresPendingDeletion -PostgresBin $PostgresBin -DataDirectory $DataDir "
        "-Purpose local -Port $Port | Out-Null\n"
        "if (-not (Test-Path -LiteralPath $sentinel)) { throw 'reused source path was deleted' }\n"
        "$receipt = Get-XpjTestPostgresDeletionReceiptPath $DataDir\n"
        "if (Test-Path -LiteralPath $receipt) { throw 'delete receipt remains' }\n",
        encoding="ascii",
    )
    for index, engine in enumerate(powershell_contract_engines()):
        port = _free_local_port()
        data_dir = tmp_path / f"partial-delete-{index}"
        tombstone_path = tmp_path / f"tombstone-{index}.txt"
        move_ready = tmp_path / f"move-{index}.ready"
        move_release = tmp_path / f"move-{index}.release"
        displaced = tmp_path / f"displaced-{index}"
        started = _run_lifecycle(
            engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        _stop_preserving_data(postgres_bin, data_dir)
        prepared = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(prepare),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
                "-TombstonePath",
                str(tombstone_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        tombstone = tombstone_path.read_text(encoding="utf-8")
        holder = subprocess.Popen(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(hold_move),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-DataDir",
                str(data_dir),
                "-Tombstone",
                tombstone,
                "-Ready",
                str(move_ready),
                "-Release",
                str(move_release),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 10
            while not move_ready.exists() and time.monotonic() < deadline:
                assert holder.poll() is None, holder.communicate(timeout=2)[0]
                time.sleep(0.05)
            assert move_ready.exists()
            with pytest.raises(OSError):
                data_dir.rename(displaced)
            assert data_dir.is_dir()
            assert not displaced.exists()
        finally:
            move_release.write_text("release", encoding="ascii")
            holder_output, _ = holder.communicate(timeout=15)
        assert holder.returncode == 0, holder_output
        assert Path(tombstone).is_dir()
        assert not data_dir.exists()
        resume_command = [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(resume),
            "-Contract",
            str(TEST_POSTGRES_CONTRACT),
            "-PostgresBin",
            str(postgres_bin),
            "-DataDir",
            str(data_dir),
            "-Port",
            str(port),
        ]

        def resume_deletion(
            command: tuple[str, ...] = tuple(resume_command),
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )

        def remove_reused_source(source: Path = data_dir) -> None:
            (source / "new-owner.txt").unlink()
            source.rmdir()

        tombstone_dir = Path(tombstone)
        original_tombstone = tmp_path / f"original-tombstone-{index}"
        tombstone_dir.rename(original_tombstone)
        tombstone_dir.mkdir()
        replacement_sentinel = tombstone_dir / "replacement.txt"
        replacement_sentinel.write_text("keep", encoding="ascii")
        replaced = resume_deletion()
        assert replaced.returncode != 0, replaced.stdout + replaced.stderr
        assert replacement_sentinel.read_text(encoding="ascii") == "keep"
        remove_reused_source()
        replacement_sentinel.unlink()
        tombstone_dir.rmdir()
        original_tombstone.rename(tombstone_dir)

        outside = tmp_path / f"outside-delete-{index}"
        outside.mkdir()
        outside_sentinel = outside / "outside.txt"
        outside_sentinel.write_text("keep", encoding="ascii")
        junction = tombstone_dir / "outside-junction"
        junction_result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert junction_result.returncode == 0, junction_result.stdout + junction_result.stderr
        reparse_refused = resume_deletion()
        assert reparse_refused.returncode != 0, reparse_refused.stdout + reparse_refused.stderr
        assert outside_sentinel.read_text(encoding="ascii") == "keep"
        remove_reused_source()
        junction.rmdir()

        resumed = resume_deletion()
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_deletion_started_recovery_does_not_require_deleted_control_files(
    tmp_path: Path,
) -> None:
    postgres_bin = _postgres_bin()
    prepare = tmp_path / "prepare-partial-delete.ps1"
    prepare.write_text(
        "param($Contract,$PostgresBin,$DataDir,$Port,$TombstonePath)\n"
        ". $Contract\n"
        "$marker = Assert-XpjTestPostgresDataOwnership -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "New-XpjTestPostgresDeletionReceipt -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port "
        "-SystemIdentifier $marker.SystemIdentifier | Out-Null\n"
        "$receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDir\n"
        "$receipt = Read-XpjTestPostgresDeletionReceipt -ReceiptPath $receiptPath "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "$tombstone = [string]$receipt.TombstoneDirectory\n"
        "$move = [XpjTestDirectoryMoveHandle]::Open($DataDir)\n"
        "try { $move.RenameTo($tombstone) } finally { $move.Dispose() }\n"
        "$identity = [XpjTestDirectoryMoveHandle]::OpenIdentity($tombstone)\n"
        "try {\n"
        "  Assert-XpjTestPostgresDeletionDirectoryInstance "
        "-PostgresBin $PostgresBin -Directory $tombstone -Receipt $receipt "
        "-Purpose local -Port $Port -DirectoryHandle $identity\n"
        "  Set-XpjTestPostgresDeletionReceiptPhase -Receipt $receipt "
        "-ReceiptPath $receiptPath -Phase deletion_started\n"
        "} finally { $identity.Dispose() }\n"
        "Remove-Item -LiteralPath (Join-Path $tombstone 'global\\pg_control') "
        "-Force -ErrorAction Stop\n"
        "[IO.File]::WriteAllText($TombstonePath,$tombstone)\n",
        encoding="ascii",
    )
    resume = tmp_path / "resume-partial-delete.ps1"
    resume.write_text(
        "param($Contract,$PostgresBin,$DataDir,$Port)\n"
        ". $Contract\n"
        "Complete-XpjTestPostgresPendingDeletion -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port | Out-Null\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        port = _free_local_port()
        data_dir = tmp_path / f"partial-control-delete-{index}"
        tombstone_path = tmp_path / f"partial-control-tombstone-{index}.txt"
        started = _run_lifecycle(
            engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        _stop_preserving_data(postgres_bin, data_dir)
        prepared = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(prepare),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
                "-TombstonePath",
                str(tombstone_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        tombstone = Path(tombstone_path.read_text(encoding="utf-8"))
        assert tombstone.is_dir()
        assert not (tombstone / "global" / "pg_control").exists()

        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(resume),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        receipt = data_dir.parent / f".{data_dir.name}.xpj-delete.receipt.json"
        assert not tombstone.exists()
        assert not receipt.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_tombstone_restored_to_source_resumes_the_same_deletion(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    probe = tmp_path / "resume-restored-source.ps1"
    probe.write_text(
        "param($Contract,$PostgresBin,$DataDir,$Port)\n"
        ". $Contract\n"
        "$marker = Assert-XpjTestPostgresDataOwnership -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "New-XpjTestPostgresDeletionReceipt -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port "
        "-SystemIdentifier $marker.SystemIdentifier | Out-Null\n"
        "$receiptPath = Get-XpjTestPostgresDeletionReceiptPath $DataDir\n"
        "$receipt = Read-XpjTestPostgresDeletionReceipt -ReceiptPath $receiptPath "
        "-DataDirectory $DataDir -Purpose local -Port $Port\n"
        "$move = [XpjTestDirectoryMoveHandle]::Open($DataDir)\n"
        "try { $move.RenameTo([string]$receipt.TombstoneDirectory) } "
        "finally { $move.Dispose() }\n"
        "Set-XpjTestPostgresDeletionReceiptPhase -Receipt $receipt "
        "-ReceiptPath $receiptPath -Phase tombstone\n"
        "[IO.Directory]::Move([string]$receipt.TombstoneDirectory, $DataDir)\n"
        "Complete-XpjTestPostgresPendingDeletion -PostgresBin $PostgresBin "
        "-DataDirectory $DataDir -Purpose local -Port $Port | Out-Null\n"
        "if (Test-Path -LiteralPath $DataDir) { throw 'restored source survived deletion' }\n"
        "if (Test-Path -LiteralPath $receiptPath) { throw 'deletion receipt survived completion' }\n",
        encoding="ascii",
    )

    for index, engine in enumerate(powershell_contract_engines()):
        port = _free_local_port()
        data_dir = tmp_path / f"restored-source-{index}"
        started = _run_lifecycle(
            engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        _stop_preserving_data(postgres_bin, data_dir)
        completed = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PostgreSQL lifecycle")
def test_live_tombstone_is_never_recursively_deleted(tmp_path: Path) -> None:
    postgres_bin = _postgres_bin()
    prepare = tmp_path / "prepare-live-tombstone.ps1"
    resume = tmp_path / "resume-live-tombstone.ps1"
    write_live_tombstone_probes(prepare, resume)
    for index, engine in enumerate(powershell_contract_engines()):
        port = _free_local_port()
        data_dir = tmp_path / f"live-tombstone-{index}"
        tombstone_path = tmp_path / f"live-tombstone-{index}.txt"
        started = _run_lifecycle(
            engine,
            START_TEST_POSTGRES,
            port=port,
            data_dir=data_dir,
            postgres_bin=postgres_bin,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        _stop_preserving_data(postgres_bin, data_dir)
        prepared = subprocess.run(
            [
                engine,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(prepare),
                "-Contract",
                str(TEST_POSTGRES_CONTRACT),
                "-PostgresBin",
                str(postgres_bin),
                "-DataDir",
                str(data_dir),
                "-Port",
                str(port),
                "-TombstonePath",
                str(tombstone_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        tombstone = Path(tombstone_path.read_text(encoding="utf-8"))
        resume_command = [
            engine,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(resume),
            "-Contract",
            str(TEST_POSTGRES_CONTRACT),
            "-PostgresBin",
            str(postgres_bin),
            "-DataDir",
            str(data_dir),
            "-Port",
            str(port),
        ]
        try:
            controller_log = tmp_path / f"live-tombstone-{index}-pg-ctl.log"
            server_log = tmp_path / f"live-tombstone-{index}-server.log"
            with controller_log.open("w", encoding="utf-8") as controller_output:
                restarted = subprocess.run(
                    [
                        str(postgres_bin / "pg_ctl.exe"),
                        "-D",
                        str(tombstone),
                        "-l",
                        str(server_log),
                        "-o",
                        f"-p {port} -c listen_addresses=127.0.0.1",
                        "-w",
                        "-t",
                        "30",
                        "start",
                    ],
                    check=False,
                    stdout=controller_output,
                    stderr=subprocess.STDOUT,
                    timeout=40,
                )
            assert restarted.returncode == 0, controller_log.read_text(
                encoding="utf-8",
                errors="replace",
            )
            refused = subprocess.run(
                resume_command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            assert refused.returncode != 0, refused.stdout + refused.stderr
            assert tombstone.is_dir()
        finally:
            if (tombstone / "postmaster.pid").is_file():
                _stop_preserving_data(postgres_bin, tombstone)
        completed = subprocess.run(
            resume_command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert not tombstone.exists()
