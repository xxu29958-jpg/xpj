"""One elevated installed action, requested by the ordinary installed Manager."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ticketbox_lifecycle.connector_schema import ConnectorOperation, parse_request, require_binding
from ticketbox_lifecycle.domain.connector import ConnectorStores, requires_configuration_token, run_connector
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_connector_channel import connect_channel
from ticketbox_lifecycle.runtime.windows_connector_host import WindowsConnectorHost
from ticketbox_lifecycle.runtime.windows_connector_peer import hold_peer, require_peer
from ticketbox_lifecycle.runtime.windows_connector_prompt import confirm_native
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root, ticketbox_program_data_root
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier


def _installed_context():
    stores = FilesystemStores.from_installed()
    binding = stores.read()
    app_dir, program_data = ticketbox_install_root(), ticketbox_program_data_root()
    if binding is None or (
        Path(binding.data_root) != program_data / "data" or binding.backend_service_name != "TicketboxBackend"
        or binding.pg_service_name != "TicketboxPg" or binding.backend_port != 8000 or binding.pg_port != 5432
    ):
        raise LifecycleViolation("connector_binding_invalid", "a supported installed instance is required")
    WindowsShipmentVerifier(app_dir, program_data).verify_installed(binding)
    return stores, binding, app_dir, program_data


def _execute(channel, peer, stores, binding, app_dir, program_data) -> int:
    request = parse_request(channel.receive(seconds=15))
    if request.initiator_sid != peer.sid:
        raise LifecycleViolation("connector_initiator_mismatch", "the request does not belong to its initiating process")
    require_binding(request, binding)
    host = WindowsConnectorHost(binding, stores, app_dir, program_data)
    reply = {"schema": "ticketbox-connector-result-v1", "operation_id": request.operation_id,
        "request_hash": request.request_hash, "ok": False, "phase": "uncommitted", "code": "connector_incomplete"}
    token = None
    try:
        # UAC is sufficient for the already-selected fixed host action. Only
        # configure asks for new input, directly in the elevated native dialog.
        host.verify_context(request)
        lifecycle = stores.as_lifecycle_stores()
        connector_stores = ConnectorStores(lifecycle.mutex, stores, stores, host.files, host)
        if requires_configuration_token(connector_stores, request):
            token = confirm_native(request, needs_token=True)
        operation = run_connector(connector_stores, request, token=token)
        reply.update(ok=True, phase=operation.phase, code=operation.result_code)
    except (LifecycleError, OSError, ValueError) as exc:
        active = stores.read_active()
        if isinstance(active, ConnectorOperation) and active.request_hash == request.request_hash:
            reply.update(phase=active.phase, code=active.result_code)
        else:
            reply["code"] = exc.code if isinstance(exc, LifecycleError) else "connector_not_committed"
    finally:
        token = None
    channel.send(reply)
    return 0 if reply["ok"] else 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="TicketboxLifecycle connector")
    parser.add_argument("command", choices=("connector",))
    parser.add_argument("--channel", required=True)
    args = parser.parse_args(argv)
    try:
        with hold_peer(os.getpid()) as helper:
            if not helper.elevated:
                raise LifecycleViolation("connector_admin_required", "connector host actions require Windows authorization")
            stores, binding, app_dir, program_data = _installed_context()
            require_peer(helper, app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe",
                session=helper.session, elevated=True)
            with connect_channel(args.channel) as channel, hold_peer(channel.peer_pid(server=True)) as manager:
                require_peer(manager, app_dir / "releases" / binding.active_release_id / "manager" / "ticketbox-manager.exe",
                    session=helper.session, elevated=False)
                channel.require_security(manager.sid)
                return _execute(channel, manager, stores, binding, app_dir, program_data)
    except (LifecycleError, OSError, ValueError, TypeError):
        # No raw exception, Token or file paths are emitted. The Manager reads
        # the durable operation after a missing/unknown reply.
        return 2
