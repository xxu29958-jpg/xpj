"""The privileged, fixed-profile host adapter. It never controls local data services."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ticketbox_lifecycle.connector_schema import ConnectorOperation, ConnectorRequest, ConnectorState, require_binding
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_ACCOUNT, SERVICE_NAME, expected_service, service_argv
from ticketbox_lifecycle.policy.windows_scm_contract import require_service_configuration
from ticketbox_lifecycle.runtime.windows_account import lookup_account_sid
from ticketbox_lifecycle.runtime.windows_connector_context import (
    public_origin_revision,
    require_no_environment_overrides,
)
from ticketbox_lifecycle.runtime.windows_connector_files import CONNECTOR_SID, WindowsConnectorFiles
from ticketbox_lifecycle.runtime.windows_connector_observation import require_metrics_owner, require_process_image
from ticketbox_lifecycle.runtime.windows_connector_scm import ConnectorScm
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver, ServiceConfiguration
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import InstallationBinding


class WindowsConnectorHost:
    def __init__(self, binding: InstallationBinding, stores, app_dir: Path, program_data: Path) -> None:
        self.binding = binding
        self.stores = stores
        self.release_root = app_dir / "releases" / binding.active_release_id
        self.backend_sid = lookup_account_sid("NT SERVICE\\" + binding.backend_service_name)
        self.files = WindowsConnectorFiles(program_data / "machine", self.backend_sid)
        self.shipment = WindowsShipmentVerifier(app_dir, program_data)
        self.scm = ConnectorScm()
        self.observer = NativeWindowsScmObserver()
        self._unfinished_creation = False

    def verify_context(self, request: ConnectorRequest) -> None:
        require_binding(request, self.stores.read())
        self.shipment.verify_installed(self.binding)
        # Closing a precise owned entry stays possible after an Owner changes
        # the address. Opening it requires the revision originally authorized.
        if request.desired_enabled or request.action == "configure":
            require_no_environment_overrides()
            revision = public_origin_revision(Path(self.binding.data_root), self.backend_sid)
            if revision != request.expected_public_origin_revision:
                raise LifecycleError("connector_origin_changed", "public address changed; this request cannot open the connector")

    def verify_owned(self, request: ConnectorRequest, state: ConnectorState | None) -> None:
        current = self.scm.state_pid()
        if current is None:
            require_metrics_owner(None)
            if request.action == "reconnect" or (request.action == "set_enabled" and request.desired_enabled):
                raise LifecycleViolation("connector_service_missing", "the owned service is missing; configure it explicitly")
            return
        observed = self.observer.observe(SERVICE_NAME)
        generation, candidate = self._service_generation(request, observed)
        owned_record = state is not None and (state.configured or state.operation_id == request.operation_id)
        if generation is None or not (owned_record or candidate):
            raise LifecycleViolation("connector_service_collision", "existing service is not owned by this connector record")
        self._require_owned_service(current, observed, generation, candidate)

    def _service_generation(self, request: ConnectorRequest, observed: ServiceConfiguration) -> tuple[int | None, bool]:
        active = self.stores.read_active()
        previous = self._closing_operation(request)
        proof = previous or active
        proof_request = previous.request if previous else request
        same_operation = isinstance(active, ConnectorOperation) and active.request_hash == request.request_hash
        configuring = (same_operation or previous is not None) and proof_request.action == "configure"
        generations = {request.expected_credential_generation}
        if previous:
            generations.add(previous.request.expected_credential_generation)
        if configuring and proof.completed_step is not None:
            generations.add(proof_request.expected_credential_generation + 1)
        generation = next((value for value in generations if value > 0 and observed.argv == self._argv(value)), None)
        candidate = (configuring and
            proof.completed_step == "credential_prepared" and generation == proof_request.expected_credential_generation + 1)
        return generation, candidate

    def _require_owned_service(self, current: tuple[int, int], observed: ServiceConfiguration, generation: int, candidate: bool) -> None:
        if lookup_account_sid(SERVICE_ACCOUNT) != CONNECTOR_SID:
            raise LifecycleViolation("connector_account_mismatch", "connector virtual account identity changed")
        expected = expected_service(self._argv(generation), CONNECTOR_SID, observed.start_type)
        self._unfinished_creation = candidate and current == (1, 0) and _is_creation_cut(observed, expected)
        if not self._unfinished_creation:
            require_service_configuration(SERVICE_NAME, observed, expected, allowed_start_types=frozenset({2, 3, 4}))
            self.scm.require_dacl()
        if current[1]:
            require_process_image(current[1], self.release_root / "connector" / "cloudflared.exe")
        require_metrics_owner(current[1] or None)
        if self.scm.state_pid() != current:
            raise LifecycleError("connector_observation_changed", "connector changed while ownership was being checked")

    def credential_identity(self, request: ConnectorRequest, generation: int, token: str | None) -> str:
        return self.files.credential_identity(generation, request.operation_id, token)

    def prepare_credential(self, request: ConnectorRequest, generation: int, token: str | None) -> None:
        self.files.prepare_credential(generation, request.operation_id, token)

    def prepare_service(self, request: ConnectorRequest, state: ConnectorState) -> None:
        current = self.scm.state_pid()
        if request.action == "remove" or not state.enabled and request.action == "set_enabled":
            if current is not None:
                self.scm.disable_and_stop()
            return
        if current is None:
            self.scm.create_stopped(self._argv(state.credential_generation))
        else:
            if self._unfinished_creation:
                self.scm.finish_creation_policy()
            self.scm.prepare_generation(self._argv(state.credential_generation))
        self._require_configuration(state.credential_generation, 3)
        if self.scm.state_pid() != (1, 0):
            raise LifecycleError("connector_candidate_running", "candidate must remain stopped before intent publication")

    def apply_desired(self, request: ConnectorRequest, state: ConnectorState) -> None:
        if self.files.read() != state:
            raise LifecycleViolation("connector_intent_changed", "published connector intent changed")
        if request.action == "remove":
            self.scm.delete_stopped()
        elif state.enabled:
            self._require_credential(state, request.operation_id)
            current = self.scm.state_pid()
            require_metrics_owner(current[1] if current and current[1] else None)
            self.scm.enable_and_start()
        elif self.scm.state_pid() is not None:
            self.scm.disable_and_stop()

    def verify_desired(self, request: ConnectorRequest, state: ConnectorState) -> None:
        current = self.scm.state_pid()
        if not state.configured:
            if current is not None:
                raise LifecycleError("connector_delete_pending", "connector service deletion is not complete")
            require_metrics_owner(None)
            return
        self._require_configuration(state.credential_generation, 2 if state.enabled else 4)
        self._require_credential(state, request.operation_id)
        if not state.enabled:
            if current != (1, 0):
                raise LifecycleError("connector_stop_pending", "connector pause is not yet verified")
            require_metrics_owner(None)
        else:
            if current is None or current[0] != 4 or not current[1]:
                raise LifecycleError("connector_process_exited", "connector is not running; public availability is unverified")
            require_process_image(current[1], self.release_root / "connector" / "cloudflared.exe")
            require_metrics_owner(current[1])
            if self.scm.state_pid() != current:
                raise LifecycleError("connector_observation_changed", "connector changed during host readback")

    def clean_credentials(self, request: ConnectorRequest, state: ConnectorState) -> None:
        if request.action in {"configure", "remove"}:
            self.files.remove_generation(request.expected_credential_generation)
        previous = self._closing_operation(request)
        if previous is not None:
            self.files.remove_generation(previous.request.expected_credential_generation)
            if previous.request.action == "configure":
                generation = previous.request.expected_credential_generation + 1
                self.files.remove_generation(generation)
                self.files.remove_candidate(generation, previous.operation_id)

    def _closing_operation(self, request: ConnectorRequest) -> ConnectorOperation | None:
        if request.closing_operation_id is None:
            return None
        active = self.stores.read_active()
        previous = active.replaced_operation if isinstance(active, ConnectorOperation) and active.operation_id == request.operation_id else active
        if not isinstance(previous, ConnectorOperation) or (previous.operation_id, previous.request_hash) != (request.closing_operation_id, request.closing_request_hash):
            raise LifecycleViolation("connector_close_changed", "the exact operation selected for closure is missing")
        return previous

    def _argv(self, generation: int) -> tuple[str, ...]:
        return service_argv(self.release_root, self.files.secrets, generation)

    def _require_configuration(self, generation: int, start_type: int) -> None:
        require_service_configuration(SERVICE_NAME, self.observer.observe(SERVICE_NAME),
            expected_service(self._argv(generation), CONNECTOR_SID, start_type), allowed_start_types=frozenset({start_type}))
        self.scm.require_dacl()

    def _require_credential(self, state: ConnectorState, operation_id: str) -> None:
        if self.files.credential_identity(state.credential_generation, operation_id) != state.tunnel_id:
            raise LifecycleViolation("connector_credential_mismatch", "credential no longer matches the committed Tunnel identity")


def _is_creation_cut(observed: ServiceConfiguration, expected: ServiceConfiguration) -> bool:
    if observed.start_type != 3:
        return False
    # CreateServiceW defaults and each following fixed ChangeServiceConfig2W
    # step are the only resumable partial policy. Foreign recovery commands,
    # triggers, accounts or arguments are never repaired by inference.
    if observed.sid_type not in {0, expected.sid_type}:
        return False
    if (observed.failure_reset_seconds, observed.failure_actions) not in {
        (0, ()), (expected.failure_reset_seconds, expected.failure_actions),
    }:
        return False
    normalized = replace(observed, sid_type=expected.sid_type,
        failure_reset_seconds=expected.failure_reset_seconds, failure_actions=expected.failure_actions,
        failure_actions_on_non_crash=expected.failure_actions_on_non_crash)
    return normalized == expected
