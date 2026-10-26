"""Ordinary-user launch of one verified Lifecycle action through Windows UAC."""

from __future__ import annotations

import ctypes
import os
import re
import secrets
from ctypes import wintypes
from dataclasses import asdict

from ticketbox_lifecycle.connector_schema import ConnectorRequest
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.windows_connector_channel import serve_channel
from ticketbox_lifecycle.runtime.windows_connector_peer import hold_peer, kernel_api, require_peer
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root, ticketbox_program_data_root
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier
from ticketbox_lifecycle.schemas import InstallationBinding


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = (("size", wintypes.DWORD), ("mask", wintypes.ULONG), ("window", wintypes.HWND),
        ("verb", wintypes.LPCWSTR), ("file", wintypes.LPCWSTR), ("parameters", wintypes.LPCWSTR),
        ("directory", wintypes.LPCWSTR), ("show", ctypes.c_int), ("instance", wintypes.HINSTANCE),
        ("id_list", ctypes.c_void_p), ("class_name", wintypes.LPCWSTR), ("class_key", wintypes.HKEY),
        ("hot_key", wintypes.DWORD), ("icon", wintypes.HANDLE), ("process", wintypes.HANDLE))


def _launch(executable, channel_id: str):
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    shell.ShellExecuteExW.restype = wintypes.BOOL
    info = _ShellExecuteInfo(size=ctypes.sizeof(_ShellExecuteInfo), mask=0x40 | 0x100 | 0x400,
        verb="runas", file=str(executable), parameters=f"connector --channel {channel_id}",
        directory=str(executable.parent), show=0)
    if not shell.ShellExecuteExW(ctypes.byref(info)) or not info.process:
        code = "connector_uac_cancelled" if ctypes.get_last_error() == 1223 else "connector_launch_failed"
        raise LifecycleError(code, "Windows authorization was cancelled or the helper could not start")
    return info.process


def run_installed_action(request: ConnectorRequest, binding_payload: dict) -> dict:
    binding = InstallationBinding(**binding_payload)
    app_dir = ticketbox_install_root()
    WindowsShipmentVerifier(app_dir, ticketbox_program_data_root()).verify_installed(binding)
    helper_path = app_dir / "bin" / "lifecycle" / "TicketboxLifecycle.exe"
    manager_path = app_dir / "releases" / binding.active_release_id / "manager" / "ticketbox-manager.exe"
    kernel = kernel_api()
    kernel.GetProcessId.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.restype = wintypes.DWORD
    with hold_peer(os.getpid()) as manager:
        require_peer(manager, manager_path, session=manager.session, elevated=False, sid=request.initiator_sid)
        channel_id = secrets.token_hex(32)
        with serve_channel(channel_id, manager.sid) as channel:
            process = _launch(helper_path, channel_id)
            try:
                expected_pid = kernel.GetProcessId(process)
                channel.accept()
                if channel.peer_pid(server=False) != expected_pid:
                    raise LifecycleViolation("connector_peer_mismatch", "unexpected process connected to the private channel")
                with hold_peer(expected_pid) as helper:
                    require_peer(helper, helper_path, session=manager.session, elevated=True)
                    channel.require_security(manager.sid)
                    channel.send(asdict(request))
                    reply = channel.receive()
            finally:
                kernel.CloseHandle(process)
    return validate_result(reply, request)


def validate_result(reply: dict, request: ConnectorRequest) -> dict:
    if (set(reply) != {"schema", "operation_id", "request_hash", "ok", "phase", "code"}
        or reply["schema"] != "ticketbox-connector-result-v1" or type(reply["ok"]) is not bool
        or reply["operation_id"] != request.operation_id or reply["request_hash"] != request.request_hash
        or not isinstance(reply["phase"], str)
        or reply["phase"] not in {"uncommitted", "prepared", "applying", "committed", "failed_recoverable", "manual_intervention"}
        or not isinstance(reply["code"], str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reply["code"]) is None
        or reply["ok"] and reply["phase"] != "committed"):
        raise LifecycleViolation("connector_result_invalid", "connector reply does not bind this action")
    return reply
