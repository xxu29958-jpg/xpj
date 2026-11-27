from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.command_io import emit_failure
from ticketbox_lifecycle.domain.restore import restore
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import OwnerPairing


def _candidate(tmp_path, monkeypatch, *, fail_at=None):
    request = replace(make_install_request(tmp_path), command="restore", schema_revision="20261023_0002")
    adapters = RecordingAdapterBundle()
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    adapters.security.owner_bootstrap_secret = lambda _request: "a-new-protected-restore-secret"
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")
    events = []
    def extract(path, **_kwargs):
        path.mkdir(parents=True)
        (path / "original").write_bytes(b"preserved-original")
        if fail_at == "extract":
            raise OSError("injected extraction interruption")
    source = SimpleNamespace(digest="a" * 64,
        identity={"dataset_id": "22222222-2222-4222-8222-222222222222", "restore_epoch": 4},
        extract_data=extract)
    def rebind(_request, _source, **_kwargs):
        events.append("identity-transaction")
        if fail_at == "unexpected":
            raise ValueError("private recovery secret must not reach the installer log")
        return OwnerPairing(pairing_code="12345678", pairing_expires_at="2026-10-25T12:00:00Z")
    @contextmanager
    def open_source(candidate, path, digest):
        assert stores.mutex._lock.locked()
        assert stores.fresh_inputs_check_count == 1
        assert path == tmp_path / "selected.tbxcold"
        assert digest == source.digest
        assert candidate.operation_id == request.operation_id
        yield source
        assert stores.mutex._lock.locked()
    platform = SimpleNamespace(open_source=open_source,
        extract_data=lambda request, source: source.extract_data(Path(request.data_root)), prepare_data=lambda *_args: None,
        rotate_credentials=lambda *_args: None, rebind_identity=rebind)
    apply = adapters.dataset.apply
    def health(request, step):
        phase = stores.read_active().phase
        events.append(phase)
        assert (stores.read() is not None) == (phase == "committed")
        if fail_at == phase:
            raise LifecycleError("injected_health_failure", "candidate did not qualify")
        return apply(request, step)
    monkeypatch.setattr(adapters.dataset, "apply", health)
    result = restore(stores.as_lifecycle_stores(), request, tmp_path / "selected.tbxcold", source.digest, platform)
    assert not stores.mutex._lock.locked()
    return result, stores, adapters, events


def test_restore_admits_writes_only_after_identity_and_candidate_health(tmp_path, monkeypatch):
    result, stores, adapters, events = _candidate(tmp_path, monkeypatch)
    assert result.ok
    assert events == ["identity-transaction", "data_ready", "committed"]
    assert stores.read().expected_restore_epoch == 5
    assert stores.read_active() is None
    assert stores.history[0].kind == "restore"
    assert adapters.scm.autostart_enabled
    assert adapters.scm.fence_calls == 1
    assert adapters.postgres.apply_calls == adapters.alembic.apply_calls == 0
    assert "owner_claim" not in adapters.applied


@pytest.mark.parametrize("failure", ["extract", "data_ready", "committed", "unexpected"])
def test_restore_failure_preserves_candidate_and_keeps_durable_fence(tmp_path, monkeypatch, failure):
    result, stores, adapters, events = _candidate(tmp_path, monkeypatch, fail_at=failure)
    assert not result.ok
    assert stores.read_active().kind == "restore"
    assert stores.read_active().phase == "failed_recoverable"
    assert not stores.history
    assert not adapters.scm.autostart_enabled
    assert adapters.scm.backend_fenced
    assert (tmp_path / "programdata/data/original").read_bytes() == b"preserved-original"
    assert result.installation_published == (failure == "committed")


def test_unexpected_restore_failure_uses_existing_terminal_report_without_private_input(tmp_path, monkeypatch, capsys):
    result, stores, adapters, _events = _candidate(tmp_path, monkeypatch, fail_at="unexpected")
    assert result.code == "restore_incomplete"
    assert stores.read_active().phase == "failed_recoverable"
    assert adapters.scm.backend_fenced and not adapters.scm.autostart_enabled
    emit_failure(result)
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.count("TicketboxLifecycle failed [restore_incomplete]") == 1
    assert "preserve source and fenced candidate" in captured.err
    assert "private recovery secret" not in captured.err


def test_r2_cross_machine_mode_reports_generation_revoked_summary_and_isolation_boundaries(
    tmp_path, monkeypatch,
):
    request = replace(make_install_request(tmp_path), command="restore", schema_revision="20261101_0001")
    adapters = RecordingAdapterBundle()
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    adapters.security.owner_bootstrap_secret = lambda _request: "a-new-protected-r2-secret"
    adapters.postgres._done.update(("start_postgres", "roles_database"))
    adapters.alembic._done.add("alembic")
    revoked_counts = {"auth_tokens": 3, "devices": 2, "pairing_codes": 1, "upload_links": 2, "invitations": 1}

    source = SimpleNamespace(
        digest="b" * 64,
        identity={"dataset_id": "22222222-2222-4222-8222-222222222222", "restore_epoch": 2},
    )

    @contextmanager
    def open_source(_candidate, _path, _digest):
        yield source

    platform = SimpleNamespace(
        open_source=open_source,
        extract_data=lambda req, _src: Path(req.data_root).mkdir(parents=True),
        prepare_data=lambda *_args: None,
        rotate_credentials=lambda *_args: None,
        rebind_identity=lambda *_args, **_kwargs: OwnerPairing(
            pairing_code="99887766",
            pairing_expires_at="2026-11-27T12:00:00Z",
            revoked_credentials_summary=revoked_counts,
        ),
    )

    with pytest.raises(LifecycleError) as unconfirmed:
        restore(
            stores.as_lifecycle_stores(),
            request,
            tmp_path / "r2.tbxcold",
            source.digest,
            platform,
            restore_mode="cross-machine",
            source_isolated_confirmed=False,
        )
    assert unconfirmed.value.code == "restore_source_isolation_required"

    with pytest.raises(LifecycleError) as bad_mode:
        restore(
            stores.as_lifecycle_stores(),
            request,
            tmp_path / "r2.tbxcold",
            source.digest,
            platform,
            restore_mode="in-place",
            source_isolated_confirmed=True,
        )
    assert bad_mode.value.code == "restore_mode_invalid"

    result = restore(
        stores.as_lifecycle_stores(),
        request,
        tmp_path / "r2.tbxcold",
        source.digest,
        platform,
        restore_mode="cross-machine",
        source_isolated_confirmed=True,
    )
    assert result.ok is True
    assert result.restore_mode == "cross_machine"
    assert result.restore_epoch == 3
    assert result.client_generation == stores.read().install_id
    assert result.revoked_credentials_summary == revoked_counts
    assert "WinCred/DPAPI" in result.client_reconnect_guidance
    assert "outbox" in result.client_reconnect_guidance
    assert result.details["source_isolated_confirmed"] is True
    assert result.details["legacy_machine_material_required"] is False


def test_r2_restore_refuses_target_with_existing_managed_connector_service(
    tmp_path: Path,
) -> None:
    request = replace(make_install_request(tmp_path), command="restore", schema_revision="20261023_0002")
    adapters = RecordingAdapterBundle()
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    stores.managed_connector_present = True
    with pytest.raises(LifecycleError) as exc_info:
        restore(
            stores.as_lifecycle_stores(),
            request,
            tmp_path / "selected.tbxcold",
            "a" * 64,
            SimpleNamespace(),
            restore_mode="cross-machine",
            source_isolated_confirmed=True,
        )
    assert exc_info.value.code == "restore_target_not_empty"
    assert stores.read() is None
    assert stores.read_active() is None
