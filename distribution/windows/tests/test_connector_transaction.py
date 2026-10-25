"""Crash cuts test durable authorization, not just a happy sequence of calls."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.connector_schema import (
    PROFILE,
    REQUEST_SCHEMA,
    STATE_SCHEMA,
    ConnectorRequest,
    ConnectorState,
    parse_operation,
    parse_request,
)
from ticketbox_lifecycle.domain.connector import ConnectorStores, run_connector
from ticketbox_lifecycle.domain.install import install_or_resume
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.mutex import ThreadMutex


def request(**changes):
    base = ConnectorRequest(REQUEST_SCHEMA, PROFILE, "configure", "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", 0, "a" * 64,
        0, 0, False, 7, "S-1-5-21-1-2-3-1001", True)
    return parse_request(asdict(replace(base, **changes)))


class Crash(BaseException):
    pass


def test_installer_refuses_connector_journal_before_any_backend_fence(tmp_path):
    machine = Machine()
    run_connector(machine.stores, request(), token="fixture-secret")
    connector = next(iter(machine.operations.history.values()))
    adapters = RecordingAdapterBundle()
    install_request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, install_request.app_dir, install_request.data_root)
    stores._active = replace(connector, phase="applying", completed_step="credential_prepared")
    with pytest.raises(LifecycleError) as rejected:
        install_or_resume(stores.as_lifecycle_stores(), install_request)
    assert rejected.value.code == "operation_conflict"
    assert adapters.applied == [] and adapters.scm.fence_calls == 0
    assert stores.read_active() is not None and stores.read_active().kind == "connector"


class Operations:
    def __init__(self, cut):
        self.active = None
        self.history = {}
        self.cut = cut

    def read_active(self):
        return self.active

    def read_committed(self, operation_id):
        return self.history.get(operation_id)

    def publish_active(self, operation):
        self.active = parse_operation(asdict(operation))
        self.cut("journal_" + str(operation.completed_step) + "_" + operation.phase)

    def archive_committed(self, operation):
        self.history[operation.operation_id] = operation
        self.cut("history_published")
        self.active = None
        self.cut("active_removed")


class State:
    def __init__(self, cut):
        self.value = None
        self.cut = cut

    def read(self):
        return self.value

    def publish(self, state):
        self.value = state
        self.cut("desired_published")


class Host:
    def __init__(self, state, cut):
        self.state = state
        self.cut = cut
        self.running = False
        self.automatic = False
        self.exists = False
        self.credentials = set()
        self.origin_revision = 7
        self.backend_running = True
        self.started_generation = None

    def verify_context(self, req):
        if (req.desired_enabled or req.action == "configure") and self.origin_revision != req.expected_public_origin_revision:
            raise LifecycleError("connector_origin_changed", "origin changed")

    def verify_owned(self, req, state):
        pass

    def credential_identity(self, req, generation, token):
        return "77777777-7777-4777-8777-777777777777"

    def prepare_credential(self, req, generation, token):
        if generation not in self.credentials:
            assert token == "fixture-secret"
            self.credentials.add(generation)
            self.cut("credential_written")

    def prepare_service(self, req, target):
        self.automatic = False
        self.cut("auto_disabled")
        self.running = False
        self.cut("service_stopped")
        if req.action != "remove":
            self.exists = True
            self.cut("service_prepared")

    def apply_desired(self, req, target):
        assert self.state.read() == target
        if target.enabled:
            assert target.credential_generation in self.credentials
            self.automatic = True
            self.cut("auto_enabled")
            self.running = True
            self.started_generation = target.credential_generation
            self.cut("service_started")
        elif req.action == "remove":
            self.exists = False
            self.cut("service_deleted")

    def verify_desired(self, req, target):
        assert self.running == self.automatic == target.enabled
        assert self.exists == target.configured

    def clean_credentials(self, req, target):
        self.credentials = {target.credential_generation} if target.configured else set()
        self.cut("credentials_cleaned")


class Machine:
    def __init__(self, fail_at=None):
        self.events = []
        self.fail_at = fail_at
        self.state = State(self.cut)
        self.host = Host(self.state, self.cut)
        self.operations = Operations(self.cut)
        req = request()
        self.binding = SimpleNamespace(**{name: getattr(req, name) for name in (
            "install_id", "dataset_id", "expected_restore_epoch", "release_manifest_sha256")})
        self.stores = ConnectorStores(ThreadMutex(), SimpleNamespace(read=lambda: self.binding),
            self.operations, self.state, self.host)

    def cut(self, name):
        self.events.append(name)
        if self.fail_at == len(self.events):
            raise Crash(name)

    def configured(self):
        self.state.value = ConnectorState(STATE_SCHEMA, PROFILE, request().install_id, request().dataset_id,
            0, "a" * 64, 4, 2, 7, True, True, "44444444-4444-4444-8444-444444444444",
            "77777777-7777-4777-8777-777777777777")
        self.host.credentials = {2}
        self.host.exists = self.host.running = self.host.automatic = True


@pytest.mark.parametrize("action", ["configure", "reconnect", "set_enabled", "remove"])
def test_every_persistent_cut_resumes_only_same_request_and_preserves_local_backend(action):
    req = request(action=action, expected_revision=4, expected_credential_generation=2,
        expected_enabled=True, desired_enabled=action in {"configure", "reconnect"})
    reference = Machine()
    reference.configured()
    run_connector(reference.stores, req, token="fixture-secret")
    for cut in range(1, len(reference.events) + 1):
        machine = Machine(fail_at=cut)
        machine.configured()
        with pytest.raises(Crash):
            run_connector(machine.stores, req, token="fixture-secret")
        assert machine.host.backend_running
        machine.fail_at = None
        result = run_connector(machine.stores, req, token="fixture-secret")
        assert result.phase == "committed"
        assert machine.operations.active is None
        assert machine.host.running == machine.host.automatic == req.desired_enabled
        assert machine.host.backend_running
        if action == "configure":
            assert machine.host.started_generation == 3 and machine.host.credentials == {3}
        if action == "remove":
            assert not machine.host.exists and not machine.host.credentials


def test_cancelled_native_input_has_no_publication_or_host_change():
    machine = Machine()
    with pytest.raises(LifecycleError, match="cancelled"):
        run_connector(machine.stores, request())
    assert machine.events == [] and machine.state.read() is None


def test_old_reconnect_cannot_override_pause_and_response_loss_does_not_repeat_host_mutations():
    machine = Machine()
    machine.configured()
    pause = request(action="set_enabled", expected_revision=4, expected_credential_generation=2,
        expected_enabled=True, desired_enabled=False)
    result = run_connector(machine.stores, pause)
    before = list(machine.events)
    assert run_connector(machine.stores, pause) == result
    assert machine.events == before
    reconnect = replace(pause, operation_id="55555555-5555-4555-8555-555555555555", action="reconnect", desired_enabled=True)
    with pytest.raises(LifecycleError, match="changed"):
        run_connector(machine.stores, reconnect)
    assert not machine.host.running and not machine.host.automatic


def test_same_operation_cannot_change_request_or_adopt_another_dataset():
    machine = Machine(fail_at=1)
    req = request()
    with pytest.raises(Crash):
        run_connector(machine.stores, req, token="fixture-secret")
    machine.fail_at = None
    with pytest.raises(LifecycleError, match="immutable"):
        run_connector(machine.stores, replace(req, desired_enabled=False), token="fixture-secret")
    machine.binding.dataset_id = "66666666-6666-4666-8666-666666666666"
    with pytest.raises(LifecycleError, match="installed instance"):
        run_connector(machine.stores, req, token="fixture-secret")
    assert not machine.host.running and machine.host.backend_running


@pytest.mark.parametrize("replacement", [False, True])
def test_changed_origin_can_close_each_unfinished_configure_cut_without_reopening_or_losing_original_error(replacement):
    req = request(expected_revision=4 if replacement else 0, expected_credential_generation=2 if replacement else 0,
        expected_enabled=replacement)
    reference = Machine()
    if replacement:
        reference.configured()
    run_connector(reference.stores, req, token="fixture-secret")
    for cut in range(1, len(reference.events)):
        machine = Machine(fail_at=cut)
        if replacement:
            machine.configured()
        with pytest.raises(Crash):
            run_connector(machine.stores, req, token="fixture-secret")
        original = machine.operations.active
        if original is None or original.phase == "committed":
            continue
        machine.fail_at = None
        machine.host.origin_revision += 2  # A -> B -> A still changes authority.
        with pytest.raises(LifecycleError, match="origin changed"):
            run_connector(machine.stores, req, token="fixture-secret")
        state = machine.state.read()
        closing = request(action="remove", operation_id="88888888-8888-4888-8888-888888888888", desired_enabled=False,
            expected_revision=state.revision if state else 0, expected_credential_generation=state.credential_generation if state else 0,
            expected_enabled=state.enabled if state else False, expected_public_origin_revision=machine.host.origin_revision,
            closing_operation_id=original.operation_id, closing_request_hash=original.request_hash)
        result = run_connector(machine.stores, closing)
        assert result.replaced_operation == original
        assert not machine.host.running and not machine.host.automatic and not machine.host.exists
        assert not machine.host.credentials and machine.host.backend_running
        assert machine.operations.active is None
        assert machine.state.read().credential_generation > req.expected_credential_generation + 1
        before = list(machine.events)
        assert run_connector(machine.stores, closing) == result
        assert machine.events == before


def test_wrong_predecessor_cannot_be_replaced_and_a_closing_request_cannot_enable():
    machine = Machine(fail_at=1)
    req = request()
    with pytest.raises(Crash):
        run_connector(machine.stores, req, token="fixture-secret")
    machine.fail_at = None
    wrong = request(action="remove", operation_id="88888888-8888-4888-8888-888888888888", desired_enabled=False,
        closing_operation_id=req.operation_id, closing_request_hash="b" * 64)
    with pytest.raises(LifecycleError, match="another lifecycle"):
        run_connector(machine.stores, wrong)
    assert machine.operations.active.request == req
    with pytest.raises(LifecycleError, match="contradicts"):
        parse_request(asdict(replace(wrong, desired_enabled=True)))
