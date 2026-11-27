"""Tests for Rev3.2 §9.8 standalone purge-data lifecycle, stopped-pgdata probe, and ACL restoration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from _uninstall_reinstall_fixtures import (
    DATASET_ID,
    INSTALL_ID,
    _installed_fixture,
    _prepare_probe_retry_fixture,
    _ProbeRetryRunner,
)
from ticketbox_lifecycle.domain.purge_data import PurgeDataRequest, purge_data
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import CompletedCommand
from ticketbox_lifecycle.runtime.windows_purge_data import WindowsPurgeDataPlatform


def test_standalone_purge_data_requires_explicit_double_confirmation_and_never_touches_external_backups(
    tmp_path: Path,
) -> None:
    req, stores, _adapters, _binding = _installed_fixture(tmp_path)
    external_backup = tmp_path / "external-usb" / "keep-safe.tbxcold"
    external_backup.parent.mkdir(parents=True)
    external_backup.write_bytes(b"external-backup-must-survive")

    stopped_runner = SimpleNamespace(
        run=lambda argv, **_kw: CompletedCommand(tuple(argv), 1060, "", "service does not exist"),
    )
    running_runner = SimpleNamespace(
        run=lambda argv, **_kw: CompletedCommand(tuple(argv), 0, "STATE : 4 RUNNING", ""),
    )

    class MatchingDatasetVerifier:
        def verify_stopped_pgdata_dataset_id(self, binding, *, app_dir, program_data_root):
            del app_dir, program_data_root
            return {
                "dataset_id": binding.dataset_id,
                "client_generation": binding.install_id,
                "restore_epoch": binding.expected_restore_epoch,
            }

    class SwappedDatasetVerifier:
        def verify_stopped_pgdata_dataset_id(self, binding, *, app_dir, program_data_root):
            del app_dir, program_data_root
            return {
                "dataset_id": "99999999-9999-4999-8999-999999999999",
                "client_generation": binding.install_id,
                "restore_epoch": binding.expected_restore_epoch,
            }

    # Add undeclared user subdirs inside data_root and machine_root to prove no wildcard deletion.
    undeclared_data = Path(req.data_root) / "user-notes" / "keep.txt"
    undeclared_data.parent.mkdir(parents=True)
    undeclared_data.write_text("do-not-delete-user-dir", encoding="utf-8")
    undeclared_machine = Path(req.program_data_root) / "machine" / "custom-audit" / "keep.txt"
    undeclared_machine.parent.mkdir(parents=True)
    undeclared_machine.write_text("do-not-delete-audit", encoding="utf-8")

    # Mismatched double confirmation refused.
    with pytest.raises(LifecycleViolation) as mismatch_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-1",
                dataset_id=DATASET_ID,
                confirm_dataset_id=INSTALL_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert mismatch_exc.value.code == "purge_confirmation_mismatch"

    # Running services refused.
    with pytest.raises(LifecycleViolation) as running_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-2",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(running_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert running_exc.value.code == "purge_services_running"

    # Swapped pgdata belonging to dataset B refused even when installation.json says dataset A!
    with pytest.raises(LifecycleViolation) as swapped_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-swapped",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="preserved_outside",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=SwappedDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert swapped_exc.value.code == "purge_dataset_identity_mismatch"
    assert (Path(req.data_root) / "pgdata" / "base" / "facts").is_file()

    # Valid standalone purge deletes ONLY declared subtrees and preserves undeclared subdirs & backups.
    result = purge_data(
        stores.as_lifecycle_stores(),
        PurgeDataRequest(
            operation_id="purge-3",
            dataset_id=DATASET_ID,
            confirm_dataset_id=DATASET_ID,
            external_backups_status="preserved_outside",
            confirm_permanent_delete=True,
            program_data_root=req.program_data_root,
        ),
        WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
    )
    assert result.ok is True
    assert result.code == "data_permanently_purged"
    assert result.installation_published is False
    assert result.details["external_backups_untouched"] is True
    assert result.details["verified_dataset_identity"]["dataset_id"] == DATASET_ID
    assert not (Path(req.data_root) / "pgdata").exists()
    assert not (Path(req.data_root) / "attachments").exists()
    assert not (Path(req.data_root) / "app").exists()
    assert not (Path(req.program_data_root) / "machine" / "installation.json").exists()
    assert not (Path(req.program_data_root) / "machine" / "secrets").exists()
    assert undeclared_data.read_text(encoding="utf-8") == "do-not-delete-user-dir"
    assert undeclared_machine.read_text(encoding="utf-8") == "do-not-delete-audit"
    assert (Path(req.program_data_root) / "backups" / "pre-upgrade.tbxcold").read_bytes() == b"pre-upgrade-backup"
    assert external_backup.read_bytes() == b"external-backup-must-survive"

    # Re-running without verified binding fails closed (stale registry/dir name cannot authorize).
    stores._binding = None
    with pytest.raises(LifecycleViolation) as unbound_exc:
        purge_data(
            stores.as_lifecycle_stores(),
            PurgeDataRequest(
                operation_id="purge-4",
                dataset_id=DATASET_ID,
                confirm_dataset_id=DATASET_ID,
                external_backups_status="none_confirmed",
                confirm_permanent_delete=True,
                program_data_root=req.program_data_root,
            ),
            WindowsPurgeDataPlatform(stopped_runner, dataset=MatchingDatasetVerifier(), app_dir=Path(req.app_dir)),
        )
    assert unbound_exc.value.code == "purge_binding_missing"


def test_purge_data_stopped_pgdata_probe_writes_ephemeral_port_matched_pgpass_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib

    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    monkeypatch.setattr(pgdata_security, "temporary_probe_access", lambda _pgdata: contextlib.nullcontext())

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    runtime_secret = "rt-pass:with\\colon-001"
    (secrets_dir / "ticketbox_runtime.password").write_text(runtime_secret + "\n", encoding="ascii")
    static_pgpass = secrets_dir / "pgpass"
    static_pgpass.write_text(
        f"127.0.0.1:5432:ticketbox:ticketbox_runtime:{runtime_secret}\n",
        encoding="ascii",
    )

    observed: dict[str, object] = {}
    returned_dataset = {"id": DATASET_ID}

    def fake_run(argv, *, env=None, **_kw):
        exe_name = Path(argv[0]).name.lower()
        if exe_name == "pg_controldata.exe":
            return CompletedCommand(
                tuple(argv),
                0,
                "Database cluster state:               shut down\n"
                "Database system identifier:           7123456789012345678\n",
                "",
            )
        if exe_name == "pg_ctl.exe":
            if "start" in argv:
                opts = argv[argv.index("-o") + 1]
                observed["pg_ctl_opts"] = opts
                assert "default_transaction_read_only=on" in opts
            elif "stop" in argv:
                observed["stopped"] = True
            return CompletedCommand(tuple(argv), 0, "", "")
        if exe_name == "psql.exe":
            port = argv[argv.index("-p") + 1]
            pgpass_path = Path(env["PGPASSFILE"])
            observed["psql_port"] = port
            observed["pgpass_path"] = pgpass_path
            observed["pgpass_text"] = pgpass_path.read_text(encoding="ascii")
            assert "PGPASSWORD" not in env
            assert runtime_secret not in " ".join(argv)
            assert pgpass_path != static_pgpass
            return CompletedCommand(
                tuple(argv),
                0,
                f"{returned_dataset['id']}|{binding.install_id}|{binding.expected_restore_epoch}\n",
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(SimpleNamespace(run=fake_run), SimpleNamespace())
    verified = adapter.verify_stopped_pgdata_dataset_id(
        binding,
        app_dir=app_dir,
        program_data_root=program_data,
    )
    assert verified == {
        "dataset_id": DATASET_ID,
        "client_generation": binding.install_id,
        "restore_epoch": binding.expected_restore_epoch,
    }
    ephemeral_port = observed["psql_port"]
    assert f"-p {ephemeral_port}" in str(observed["pg_ctl_opts"])
    expected_entry = f"127.0.0.1:{ephemeral_port}:ticketbox:ticketbox_runtime:rt-pass\\:with\\\\colon-001"
    assert expected_entry in str(observed["pgpass_text"])
    assert observed["stopped"] is True
    assert not Path(observed["pgpass_path"]).exists()
    assert not Path(observed["pgpass_path"]).parent.exists()

    # Swapped dataset B in stopped pgdata must fail closed and still clean up ephemeral pgpass!
    returned_dataset["id"] = "99999999-9999-4999-8999-999999999999"
    with pytest.raises(LifecycleViolation) as mismatch_exc:
        adapter.verify_stopped_pgdata_dataset_id(
            binding,
            app_dir=app_dir,
            program_data_root=program_data,
        )
    assert mismatch_exc.value.code == "purge_dataset_identity_mismatch"
    assert not Path(observed["pgpass_path"]).exists()
    assert not Path(observed["pgpass_path"]).parent.exists()


def test_purge_data_probe_creates_pgpass_before_start_and_stops_on_psql_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib
    import tempfile

    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    monkeypatch.setattr(pgdata_security, "temporary_probe_access", lambda _pgdata: contextlib.nullcontext())

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    # 1) If mkdtemp fails, pg_ctl start must NEVER be invoked.
    events: list[str] = []

    class TrackingRunner:
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    events.append(f"start:{Path(argv[0]).name}")
                    return CompletedCommand(tuple(argv), 0, "", "")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

        def run(self, argv, **_kw):
            exe = Path(argv[0]).name.lower()
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            if exe == "psql.exe":
                events.append("psql_raise")
                raise LifecycleError("command_outcome_unknown", "psql timed out")
            if exe == "pg_ctl.exe" and "stop" in argv:
                events.append("pg_ctl_stop")
                return CompletedCommand(tuple(argv), 0, "", "")
            raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(TrackingRunner(), SimpleNamespace())
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_kw: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert events == []

    # 2) If psql raises, pg_ctl stop STILL runs, job closes, and ephemeral pgpass dir is removed.
    monkeypatch.setattr(tempfile, "mkdtemp", real_mkdtemp)
    with pytest.raises(LifecycleError) as exc_info:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert exc_info.value.code == "command_outcome_unknown"
    assert events == ["job_enter", "start:pg_ctl.exe", "psql_raise", "pg_ctl_stop", "job_exit"]
    assert list(secrets_dir.glob("purge-probe-*")) == []


def test_purge_data_probe_stops_on_pg_ctl_start_failure_or_timeout_and_temporarily_grants_then_restores_pgdata_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime import windows_security_native as native
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    req, _stores, _adapters, binding = _installed_fixture(tmp_path)
    app_dir = Path(req.app_dir)
    program_data = Path(req.program_data_root)
    pg_bin = app_dir / "postgresql" / "bin"
    pg_bin.mkdir(parents=True, exist_ok=True)
    for exe in ("pg_ctl.exe", "psql.exe", "pg_controldata.exe"):
        (pg_bin / exe).write_bytes(b"exe")
    pgdata = Path(binding.data_root) / "pgdata"
    (pgdata / "global").mkdir(parents=True, exist_ok=True)
    (pgdata / "global" / "pg_control").write_bytes(b"pg-control")
    secrets_dir = program_data / "machine" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ticketbox_runtime.password").write_text("rt-secret\n", encoding="ascii")
    (secrets_dir / "pgpass").write_text("127.0.0.1:5432:ticketbox:ticketbox_runtime:rt-secret\n", encoding="ascii")

    caller_sid = "S-1-5-21-1000-2000-3000-1001"
    sealed_dacl = (
        "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )
    events: list[str] = []
    start_mode = {"value": "nonzero"}

    monkeypatch.setattr(pgdata_security.os, "name", "nt")
    monkeypatch.setattr(native, "current_process_user_sid", lambda: caller_sid)
    monkeypatch.setattr(native, "_object_dacl_sddl", lambda _p: sealed_dacl)
    monkeypatch.setattr(native, "file_owner_sid", lambda _p: native.ADMINISTRATORS_SID)
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda _p, sddl, *, code: events.append(f"dacl:{code}:{sddl}"),
    )

    class ProbeRunner:
        def open_managed_job(self):
            class Job:
                def __enter__(self_job):
                    events.append("job_enter")
                    return self_job

                def run_background_starter(self_job, argv, **_kw):
                    events.append("pg_ctl_start")
                    if start_mode["value"] == "nonzero":
                        return CompletedCommand(tuple(argv), 1, "", "timed out waiting for server")
                    if start_mode["value"] == "timeout":
                        raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")
                    return CompletedCommand(tuple(argv), 0, "", "")

                def __exit__(self_job, *_exc):
                    events.append("job_exit")

            return Job()

        def run(self, argv, **_kw):
            exe = Path(argv[0]).name.lower()
            if exe == "pg_controldata.exe":
                return CompletedCommand(
                    tuple(argv),
                    0,
                    "Database cluster state:               shut down\n"
                    "Database system identifier:           7123456789012345678\n",
                    "",
                )
            if exe == "pg_ctl.exe" and "stop" in argv:
                events.append("pg_ctl_stop")
                return CompletedCommand(tuple(argv), 0, "", "")
            if exe == "psql.exe":
                events.append("psql_ok")
                return CompletedCommand(
                    tuple(argv),
                    0,
                    f"{DATASET_ID}|{binding.install_id}|{binding.expected_restore_epoch}\n",
                    "",
                )
            raise AssertionError(f"unexpected command: {argv}")

    adapter = WindowsDatasetAdapter(ProbeRunner(), SimpleNamespace())

    # 1) pg_ctl start returns non-zero (e.g. -w -t 30 wait timeout): MUST still run pg_ctl stop before job_exit AND restore exact DACL!
    with pytest.raises(LifecycleViolation) as nonzero_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert nonzero_exc.value.code == "purge_dataset_identity_unverifiable"
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]

    # 2) pg_ctl start raises timeout exception: MUST still run pg_ctl stop before job_exit AND restore exact DACL!
    events.clear()
    start_mode["value"] = "timeout"
    with pytest.raises(LifecycleError) as timeout_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert timeout_exc.value.code == "command_outcome_unknown"
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]

    # 3) Success path: temporary user SID granted before start, exact original DACL restored after stop + job_exit.
    events.clear()
    start_mode["value"] = "ok"
    verified = adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert verified["dataset_id"] == DATASET_ID
    assert events == [
        f"dacl:purge_probe_acl_failed:{sealed_dacl}(A;OICI;FA;;;{caller_sid})",
        "job_enter",
        "pg_ctl_start",
        "psql_ok",
        "pg_ctl_stop",
        "job_exit",
        f"dacl:purge_probe_acl_restore_failed:{sealed_dacl}",
    ]
    assert list(secrets_dir.glob("purge-probe-*")) == []


def test_temporary_probe_access_restores_probe_created_owners_and_fails_closed_on_any_restore_or_verify_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime import windows_pgdata_security as pgdata_security
    from ticketbox_lifecycle.runtime import windows_security_native as native

    pgdata = tmp_path / "pgdata"
    (pgdata / "global").mkdir(parents=True)
    pg_control = pgdata / "global" / "pg_control"
    pg_control.write_bytes(b"pg-control")
    postmaster_opts = pgdata / "postmaster.opts"

    caller_sid = "S-1-5-21-1000-2000-3000-1001"
    sealed_dacl = (
        "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
    )

    state_dacl: dict[Path, str] = {pgdata: sealed_dacl, pgdata / "global": sealed_dacl, pg_control: sealed_dacl}
    state_owner: dict[Path, str] = {
        pgdata: native.ADMINISTRATORS_SID,
        pgdata / "global": native.ADMINISTRATORS_SID,
        pg_control: native.ADMINISTRATORS_SID,
    }
    owner_restores: list[tuple[Path, str]] = []

    def fake_apply_dacl(path: Path, sddl: str, *, code: str) -> None:
        del code
        state_dacl[path] = sddl
        for parent, dirs, files in __import__("os").walk(path, followlinks=False):
            for name in (*dirs, *files):
                state_dacl[Path(parent) / name] = sddl

    def fake_set_owner(path: Path, owner: str, *, code: str) -> None:
        del code
        owner_restores.append((path, owner))
        state_owner[path] = owner

    monkeypatch.setattr(pgdata_security.os, "name", "nt")
    monkeypatch.setattr(native, "current_process_user_sid", lambda: caller_sid)
    monkeypatch.setattr(native, "_object_dacl_sddl", lambda p: state_dacl[p])
    monkeypatch.setattr(native, "file_owner_sid", lambda p: state_owner[p])
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 1) Probe creates a new file owned by caller_sid: owner is restored to Administrators and full-tree check passes.
    with pgdata_security.temporary_probe_access(pgdata):
        postmaster_opts.write_text("opts", encoding="ascii")
        state_dacl[postmaster_opts] = f"{sealed_dacl}(A;OICI;FA;;;{caller_sid})"
        state_owner[postmaster_opts] = caller_sid
    assert owner_restores == [(postmaster_opts, native.ADMINISTRATORS_SID)]
    assert state_owner[postmaster_opts] == native.ADMINISTRATORS_SID
    assert caller_sid not in state_dacl[postmaster_opts]

    # 2) Reading root owner fails before grant -> fail-closed with purge_probe_acl_failed (never skipped).
    monkeypatch.setattr(native, "file_owner_sid", lambda _p: (_ for _ in ()).throw(OSError(5, "denied")))
    with pytest.raises(LifecycleError) as root_owner_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when root owner cannot be read")
    assert root_owner_exc.value.code == "purge_probe_acl_failed"
    monkeypatch.setattr(native, "file_owner_sid", lambda p: state_owner[p])

    # 3) Restoring a probe-created file owner fails -> never silently suppressed (merges with body error if any).
    monkeypatch.setattr(
        pgdata_security,
        "set_owner_sid",
        lambda _p, _o, *, code: (_ for _ in ()).throw(LifecycleError(code, "owner restore denied")),
    )
    with pytest.raises(LifecycleError) as owner_fail_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[postmaster_opts] = caller_sid
            raise LifecycleViolation("purge_dataset_identity_mismatch", "dataset mismatch")
    assert owner_fail_exc.value.code == "purge_probe_owner_restore_failed"
    assert "purge_dataset_identity_mismatch" in owner_fail_exc.value.message
    state_owner[postmaster_opts] = native.ADMINISTRATORS_SID
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 4) Residual caller_sid ACE left on a child file after restore -> full-tree verification fails closed!
    def leaky_apply_dacl(path: Path, sddl: str, *, code: str) -> None:
        del code
        state_dacl[path] = sddl
        if caller_sid in sddl:
            state_dacl[pg_control] = sddl

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", leaky_apply_dacl)
    with pytest.raises(LifecycleError) as residual_ace_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert residual_ace_exc.value.code == "purge_probe_acl_restore_failed"

    # 5) Residual caller_sid owner left on a child file after restore -> full-tree verification fails closed!
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)
    monkeypatch.setattr(pgdata_security, "set_owner_sid", lambda _p, _o, *, code: None)
    with pytest.raises(LifecycleError) as residual_owner_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[postmaster_opts] = caller_sid
    assert residual_owner_exc.value.code == "purge_probe_owner_restore_failed"
    state_owner[postmaster_opts] = native.ADMINISTRATORS_SID
    monkeypatch.setattr(pgdata_security, "set_owner_sid", fake_set_owner)

    # 6) Untrusted root owner (neither SYSTEM nor Administrators) -> refuse before touching DACL or running body!
    state_owner[pgdata] = "S-1-5-21-1000-2000-3000-1099"
    with pytest.raises(LifecycleError) as untrusted_root_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when root owner is untrusted")
    assert untrusted_root_exc.value.code == "purge_probe_owner_untrusted"
    state_owner[pgdata] = native.ADMINISTRATORS_SID

    # 6b) Unprotected (inheriting) root DACL (D:AI...) lacking caller_sid -> refuse WITHOUT mutating DACL!
    applied_calls: list[str] = []
    monkeypatch.setattr(
        pgdata_security,
        "apply_protected_dacl",
        lambda _p, sddl, *, code: applied_calls.append(f"{code}:{sddl}"),
    )
    state_dacl[pgdata] = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
    with pytest.raises(LifecycleError) as unprotected_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run on unprotected inheriting pgdata root DACL")
    assert unprotected_exc.value.code == "purge_probe_acl_unprotected"
    assert applied_calls == []
    state_dacl[pgdata] = sealed_dacl
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)

    # 7) Root owner drifts during probe -> post-exit verification catches it and fails closed!
    with pytest.raises(LifecycleError) as root_drift_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            state_owner[pgdata] = caller_sid
    assert root_drift_exc.value.code == "purge_probe_acl_restore_failed"
    state_owner[pgdata] = native.ADMINISTRATORS_SID

    # 7b) Readback root DACL control flag drifts from D:PAI to D:P -> fails closed!
    def ctrl_drift_apply(path: Path, sddl: str, *, code: str) -> None:
        fake_apply_dacl(path, sddl, code=code)
        if code == "purge_probe_acl_restore_failed":
            state_dacl[path] = sddl.replace("D:PAI(", "D:P(", 1)

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", ctrl_drift_apply)
    with pytest.raises(LifecycleError) as ctrl_drift_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert ctrl_drift_exc.value.code == "purge_probe_acl_restore_failed"
    state_dacl[pgdata] = sealed_dacl

    # 7c) Readback root DACL preserves ACE set but swaps ACE order (e.g. Allow/Deny reordering) -> fails closed!
    def order_swap_apply(path: Path, sddl: str, *, code: str) -> None:
        fake_apply_dacl(path, sddl, code=code)
        if code == "purge_probe_acl_restore_failed":
            state_dacl[path] = (
                "D:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
                "(A;OICI;FA;;;S-1-5-80-1-2-3-4-5)(A;;RC;;;OW)(A;OICIIO;RC;;;OW)"
            )

    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", order_swap_apply)
    with pytest.raises(LifecycleError) as order_swap_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert order_swap_exc.value.code == "purge_probe_acl_restore_failed"
    state_dacl[pgdata] = sealed_dacl
    monkeypatch.setattr(pgdata_security, "apply_protected_dacl", fake_apply_dacl)

    # 8) Unreadable subdirectory during os.walk triggers onerror -> fails closed (never silently skips subtree)!
    import os as _os

    real_walk = _os.walk

    def unreadable_walk(top, *args, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "locked-pg-sub")))
        return iter(())

    monkeypatch.setattr(pgdata_security.os, "walk", unreadable_walk)
    with pytest.raises(LifecycleError) as walk_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            raise AssertionError("body must not run when pgdata tree is unreadable")
    assert walk_exc.value.code == "pgdata_tree_unreadable"

    # Also verify onerror during exit restore/verify when unreadable subdir appears after entry:
    walk_calls = {"count": 0}

    def fail_on_restore_walk(top, *args, onerror=None, **kwargs):
        walk_calls["count"] += 1
        if walk_calls["count"] >= 2 and onerror is not None:
            onerror(PermissionError(13, "denied", str(Path(top) / "locked-during-restore")))
            return iter(())
        return real_walk(top, *args, onerror=onerror, **kwargs)

    monkeypatch.setattr(pgdata_security.os, "walk", fail_on_restore_walk)
    with pytest.raises(LifecycleError) as restore_walk_exc:
        with pgdata_security.temporary_probe_access(pgdata):
            pass
    assert restore_walk_exc.value.code == "pgdata_tree_unreadable"
    monkeypatch.setattr(pgdata_security.os, "walk", real_walk)


def test_purge_data_probe_retries_stop_until_clean_shutdown_verified_and_never_swallows_stop_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter

    binding, app_dir, program_data, pgdata = _prepare_probe_retry_fixture(tmp_path, monkeypatch)

    def _timeout_after_pid(on_timeout: Callable[[], None] | None) -> None:
        runner.events.append("pg_ctl_start_timeout")
        runner.cluster_running = True
        (pgdata / "postmaster.pid").write_text("12345\n", encoding="ascii")
        if on_timeout is not None:
            on_timeout()
        raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")

    def _delayed_pid_start(on_timeout: Callable[[], None] | None) -> None:
        runner.events.append("pg_ctl_start_timeout_before_pid")
        if on_timeout is not None:
            on_timeout()
        runner.cluster_running = True
        (pgdata / "postmaster.pid").write_text("54321\n", encoding="ascii")
        runner.events.append("delayed_pid_created")
        raise LifecycleError("command_outcome_unknown", "pg_ctl start timed out")

    def _unconfirmed_exit_start(on_timeout: Callable[[], None] | None) -> None:
        del on_timeout
        runner.events.append("starter_not_exited")
        raise LifecycleError("starter_process_not_exited", "pg_ctl.exe did not confirm exit")

    runner = _ProbeRetryRunner(pgdata, _timeout_after_pid)
    adapter = WindowsDatasetAdapter(runner, SimpleNamespace())

    with pytest.raises(LifecycleError) as retry_ok_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert retry_ok_exc.value.code == "command_outcome_unknown"
    assert runner.events == ["job_enter", "pg_ctl_start_timeout", "pg_ctl_stop_1", "pg_ctl_stop_2", "job_exit"]

    runner.reset(stop_succeeds_on=99)
    with pytest.raises(LifecycleError) as stop_fail_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert stop_fail_exc.value.code == "purge_probe_stop_failed"
    assert "command_outcome_unknown" in stop_fail_exc.value.message
    assert runner.events == ["job_enter", "pg_ctl_start_timeout", "pg_ctl_stop_1", "pg_ctl_stop_2", "job_exit"]

    runner.reset(stop_succeeds_on=2, on_start=_delayed_pid_start)
    with pytest.raises(LifecycleError) as delayed_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert delayed_exc.value.code == "command_outcome_unknown"
    assert not (pgdata / "postmaster.pid").exists()
    assert runner.cluster_running is False
    assert runner.events == [
        "job_enter",
        "pg_ctl_start_timeout_before_pid",
        "pg_ctl_stop_1",
        "delayed_pid_created",
        "pg_ctl_stop_2",
        "job_exit",
    ]

    runner.reset(stop_succeeds_on=1, on_start=_unconfirmed_exit_start)
    with pytest.raises(LifecycleError) as unconfirmed_exc:
        adapter.verify_stopped_pgdata_dataset_id(binding, app_dir=app_dir, program_data_root=program_data)
    assert unconfirmed_exc.value.code == "purge_probe_stop_failed"
    assert isinstance(unconfirmed_exc.value.__cause__, LifecycleError)
    assert unconfirmed_exc.value.__cause__.code == "starter_process_not_exited"
    assert runner.events == ["job_enter", "starter_not_exited", "pg_ctl_stop_1", "job_exit"]
