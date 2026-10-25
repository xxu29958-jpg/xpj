from dataclasses import replace
from types import SimpleNamespace

import pytest

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.cli import _emit_failure
from ticketbox_lifecycle.restore_cli import _restore_candidate
from ticketbox_lifecycle.schemas import OwnerPairing
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request


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
    platform = SimpleNamespace(runner=None, prepare_data=lambda *_args: None,
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
    result = _restore_candidate(stores.as_lifecycle_stores(), request, source, platform)
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
    _emit_failure(result)
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.count("TicketboxLifecycle failed [restore_incomplete]") == 1
    assert "preserve source and fenced candidate" in captured.err
    assert "private recovery secret" not in captured.err
