"""A missing helper reply never creates another action or claims another result."""

from __future__ import annotations

from dataclasses import replace
from threading import Thread
from types import SimpleNamespace

import pytest
from ticketbox_lifecycle.connector_schema import (
    OPERATION_SCHEMA,
    PROFILE,
    STATE_SCHEMA,
    ConnectorOperation,
    ConnectorState,
)
from ticketbox_lifecycle.errors import LifecycleError

from backend_manager.connector_action import validate_result
from backend_manager.connector_control import ConnectorControl
from backend_manager.connector_projection import ConnectorProjection
from backend_manager.public_connectivity_provider import PublicConnectivityProviderClosedError

_SID = "S-1-5-21-1-2-3-1001"
_BINDING = {
    "schema": "ticketbox-installation-binding-v1",
    "install_id": "22222222-2222-4222-8222-222222222222",
    "dataset_id": "33333333-3333-4333-8333-333333333333",
    "expected_restore_epoch": 0,
    "release_manifest_sha256": "a" * 64,
    "data_root": "C:/ProgramData/Ticketbox/data/generation-1",
    "active_release_id": "fixture-release", "previous_release_id": None,
    "postgres_major": 17, "pg_service_name": "TicketboxPostgres",
    "backend_service_name": "TicketboxBackend", "pg_port": 15432,
    "backend_port": 8000, "health_attestation_key": "fixture-key",
}
_IDENTITY = {key: _BINDING[key] for key in (
    "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256",
)}


def _operation(request, phase):
    return ConnectorOperation(OPERATION_SCHEMA, "connector", "connector_only", request.operation_id,
        request.request_hash, request, phase, "host_applied" if phase == "committed" else "credential_prepared",
        "host_committed_public_unverified" if phase == "committed" else "connector_scm_failed")


class _Public:
    def __init__(self, *, closed=False):
        self.refreshes = []
        self.ended = 0
        self.closed = closed

    def begin_authority_mutation(self):
        pass

    def end_authority_mutation(self):
        self.ended += 1

    def request_refresh(self, *, full):
        if self.closed:
            raise PublicConnectivityProviderClosedError("closed")
        self.refreshes.append(full)


@pytest.mark.parametrize("failure", ["action", "refresh"])
def test_worker_reports_unexpected_failure_without_leaking_or_repeating(failure, monkeypatch, capsys):
    from backend_manager import connector_control

    secret = "private-token-must-not-escape-the-worker"
    requests, workers, unhandled = [], [], []
    public = _Public()

    def fail():
        raise AssertionError(secret)

    def runner(request, _binding):
        requests.append(request)
        if failure == "action":
            fail()
        return {"ok": True}

    def refresh(*, full):
        if failure == "refresh":
            fail()

    def thread(**kwargs):
        worker = Thread(**kwargs)
        workers.append(worker)
        return worker

    public.request_refresh = refresh
    monkeypatch.setattr(connector_control.threading, "Thread", thread)
    monkeypatch.setattr(connector_control.threading, "excepthook", unhandled.append)
    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", _BINDING), public,
        runner=runner, reader=lambda *_args: ConnectorProjection(_IDENTITY, 7, None, None, False), sid_reader=lambda: _SID)
    control.start("configure", True)
    assert len(workers) == 1
    workers[0].join(timeout=2)
    assert not workers[0].is_alive()
    assert len(requests) == 1 and public.ended == 1 and not unhandled
    status = control.snapshot()
    assert status["state"] == "unknown" and "刷新" in status["message"] and "诊断" in status["message"]
    captured = capsys.readouterr()
    assert secret not in str(status) + captured.out + captured.err


@pytest.mark.parametrize("observed", ["committed", "failed_recoverable", "origin_changed", "different_request", "different_binding", "unreadable"])
def test_lost_reply_reads_once_and_only_recognizes_the_exact_bound_operation(observed):
    initial = ConnectorProjection(_IDENTITY, 7, None, None, False)
    facts = SimpleNamespace(projection=initial, binding=dict(_BINDING), requests=[], reads=0)

    def read(*_args):
        facts.reads += 1
        if facts.requests and observed == "unreadable":
            raise OSError("projection unavailable")
        return facts.projection

    def runner(request, _binding):
        facts.requests.append(request)
        replay = replace(request, desired_enabled=False) if observed == "different_request" else request
        operation = _operation(replay, "failed_recoverable" if observed in {"failed_recoverable", "origin_changed"} else "committed")
        facts.projection = replace(initial, operation=operation, busy=operation.phase != "committed",
            origin_revision=8 if observed == "origin_changed" else 7)
        if observed == "different_binding":
            facts.binding["expected_restore_epoch"] = 1
        raise LifecycleError("connector_channel_closed", "reply was lost after the host action")

    public = _Public()
    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", facts.binding), public,
        runner=runner, reader=read, sid_reader=lambda: _SID)
    control._work("configure", True)
    assert len(facts.requests) == 1
    assert facts.reads == (1 if observed == "different_binding" else 2)
    assert public.ended == 1 and public.refreshes == [True]
    status = control.snapshot()
    expected = {"committed": "succeeded", "failed_recoverable": "incomplete", "origin_changed": "incomplete"}.get(observed, "unknown")
    assert status["state"] == expected
    if observed == "origin_changed":
        assert "关闭未完成的配置" in status["message"]
    elif expected == "unknown":
        assert "刷新" in status["message"] and "诊断" in status["message"]


def test_continue_reuses_the_original_request_and_does_not_require_new_input():
    initial = ConnectorProjection(_IDENTITY, 7, None, None, False)
    original = initial.request("configure", enabled=True, sid=_SID)
    current = replace(initial, operation=_operation(original, "failed_recoverable"), busy=True)
    sent = []

    def runner(request, _binding):
        sent.append(request)
        return {"ok": True}

    public = _Public(closed=True)
    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", _BINDING), public,
        runner=runner, reader=lambda *_args: current, sid_reader=lambda: _SID)
    control._work("continue", False)
    assert sent == [original]
    assert sent[0] is original
    assert control.snapshot()["state"] == "succeeded"
    assert public.ended == 1


@pytest.mark.parametrize(("phase", "code", "expected", "can_continue"), [
    ("uncommitted", "connector_token_invalid", "凭据格式无效", False),
    ("uncommitted", "connector_not_committed", "本次操作未提交", False),
    ("failed_recoverable", "connector_scm_failed", "可继续上次操作", True),
    ("manual_intervention", "connector_credential_mismatch", "查看连接详情并导出诊断", False),
])
def test_failed_reply_only_offers_continuation_for_a_resumable_operation(phase, code, expected, can_continue):
    projection = ConnectorProjection(_IDENTITY, 7, None, None, False)
    requests = []
    public = _Public()

    def runner(request, _binding):
        requests.append(request)
        return {"ok": False, "phase": phase, "code": code}

    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", _BINDING), public,
        runner=runner, reader=lambda *_args: projection, sid_reader=lambda: _SID)
    control._work("configure", True)
    status = control.snapshot()
    assert status["state"] == "incomplete" and expected in status["message"]
    assert ("可继续上次操作" in status["message"]) is can_continue
    assert len(requests) == 1 and public.refreshes == [True]
    if phase == "uncommitted":
        assert "继续" not in status["message"]


def test_continue_cannot_reassign_another_users_request():
    initial = ConnectorProjection(_IDENTITY, 7, None, None, False)
    original = initial.request("configure", enabled=True, sid=_SID)
    current = replace(initial, operation=_operation(original, "failed_recoverable"), busy=True)
    sent = []
    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", _BINDING), _Public(),
        runner=lambda *args: sent.append(args), reader=lambda *_args: current, sid_reader=lambda: _SID + "2")
    control._work("continue", False)
    assert sent == []
    assert control.snapshot()["state"] == "failed"


@pytest.mark.parametrize("interrupted", [False, True])
def test_replacing_a_paused_connections_credential_keeps_the_pause(interrupted):
    state = ConnectorState(STATE_SCHEMA, PROFILE, **_IDENTITY, revision=3, credential_generation=2,
        public_origin_revision=7, enabled=False, configured=True,
        operation_id="44444444-4444-4444-8444-444444444444", tunnel_id="55555555-5555-4555-8555-555555555555")
    projection = ConnectorProjection(_IDENTITY, 7, state, None, False)
    current = [projection]
    sent = []

    def runner(request, _binding):
        sent.append(request)
        if interrupted:
            current[0] = replace(projection, origin_revision=8,
                operation=_operation(request, "failed_recoverable"), busy=True)
            raise LifecycleError("connector_channel_closed", "reply lost and Owner changed the address")
        return {"ok": True}

    control = ConnectorControl(lambda: ("http://127.0.0.1:8000", "fixture-session", _BINDING), _Public(),
        runner=runner, reader=lambda *_args: current[0], sid_reader=lambda: _SID)
    control._work("configure", True)
    assert len(sent) == 1 and not sent[0].desired_enabled
    assert ("关闭未完成的配置" if interrupted else "公网保持暂停") in control.snapshot()["message"]


@pytest.mark.parametrize("changes", [{"code": ""}, {"phase": []}, {"operation_id": "other"}, {"request_hash": "b" * 64}, {"code": "secret token"}, {"phase": "applying"}])
def test_helper_result_must_bind_the_exact_request_and_closed_result(changes):
    request = ConnectorProjection(_IDENTITY, 7, None, None, False).request("configure", enabled=True, sid=_SID)
    result = {"schema": "ticketbox-connector-result-v1", "operation_id": request.operation_id,
        "request_hash": request.request_hash, "ok": True, "phase": "committed", "code": "host_committed_public_unverified"}
    assert validate_result(result, request) == result
    with pytest.raises(LifecycleError, match="connector reply"):
        validate_result({**result, **changes}, request)
