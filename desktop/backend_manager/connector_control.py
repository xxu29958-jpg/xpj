"""Coordinate fixed host actions and automatic public verification for the UI."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress

from ticketbox_lifecycle.connector_schema import require_binding
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.schemas import InstallationBinding

from backend_manager.connector_action import run_installed_action
from backend_manager.connector_projection import read_connector_projection
from backend_manager.product_data import ProductDataError
from backend_manager.public_connectivity_provider import PublicConnectivityProviderClosedError
from backend_manager.windows_user_security import current_user_sid


class ConnectorControl:
    def __init__(self, context: Callable, public, *, runner=run_installed_action, sid_reader=current_user_sid,
        reader=read_connector_projection) -> None:
        self._context, self._public, self._runner = context, public, runner
        self._sid_reader, self._reader = sid_reader, reader
        self._lock = threading.Lock()
        self._status = {"state": "idle", "message": ""}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _set(self, state: str, message: str) -> None:
        with self._lock:
            self._status = {"state": state, "message": message}

    def start(self, action: str, enabled: bool = False) -> None:
        with self._lock:
            if self._status["state"] == "running":
                return
            self._status = {"state": "running", "message": "正在处理，请完成 Windows 授权。"}
        self._public.begin_authority_mutation()
        try:
            threading.Thread(target=self._work, args=(action, enabled), name="ticketbox-connector-action", daemon=True).start()
        except RuntimeError:
            self._public.end_authority_mutation()
            self._set("failed", "暂时无法开始，请稍后重试。")

    def _request(self, projection, action: str, enabled: bool):
        sid = self._sid_reader()
        if action == "continue":
            if not projection.busy or projection.operation is None:
                return None
            action, enabled = projection.operation.request.action, projection.operation.request.desired_enabled
        elif action == "configure" and projection.state is not None and projection.state.configured:
            enabled = projection.state.enabled
        return projection.request(action, enabled=enabled, sid=sid)

    def _completed(self, request) -> None:
        message = "本机操作已完成，正在检查公网连接。"
        if request.action == "remove":
            message = "本机连接已移除。远端凭据仍需在 Cloudflare 撤销；共享连接需先确认影响范围。"
        elif not request.desired_enabled:
            message = ("连接凭据已更新，公网保持暂停。" if request.action == "configure" else "公网已暂停。")
            message += "重启电脑后仍保持暂停，本地账本可正常使用。"
        self._set("succeeded", message)

    def _incomplete(self, code: str) -> None:
        if code == "connector_origin_changed":
            message = "公网地址已变化，上次操作不能继续开放连接。请关闭未完成的配置，再重新设置。"
        elif code in {"connector_binding_changed", "connector_stale_request", "connector_request_changed"}:
            message = "安装或连接记录已变化，不能继续这次操作。请重新打开管理器，查看当前状态。"
        elif code in {"connector_service_collision", "connector_account_mismatch", "connector_metrics_collision", "scm_configuration_mismatch", "connector_scm_security_changed"}:
            message = "检测到其他连接或服务配置冲突，未接管该服务。请查看连接详情并导出诊断。"
        else:
            message = "操作尚未完成。可继续上次操作；若仍失败，请导出诊断。本地账本仍可使用。"
        self._set("incomplete", message)

    def _reconcile(self, request) -> None:
        # One read of the existing authority, never a retry loop or a new action.
        self._set("unknown", "尚未确认结果。请刷新连接状态；如仍无法确认，请导出诊断。本地账本仍可使用。")
        if request is None:
            return
        try:
            origin, token, binding = self._context()
            require_binding(request, InstallationBinding(**binding))
            projection = self._reader(origin, token, binding)
            operation = projection.operation
            if operation is None or (operation.operation_id, operation.request_hash) != (request.operation_id, request.request_hash):
                return
            if operation.phase == "committed":
                self._completed(request)
            elif projection.busy:
                if (request.desired_enabled or request.action == "configure") and request.expected_public_origin_revision != projection.origin_revision:
                    self._incomplete("connector_origin_changed")
                else:
                    self._incomplete(operation.result_code)
        except (ProductDataError, LifecycleError, OSError, ValueError, TypeError, RuntimeError):
            return

    def _work(self, action: str, enabled: bool) -> None:
        request = None
        try:
            origin, token, binding = self._context()
            projection = self._reader(origin, token, binding)
            request = self._request(projection, action, enabled)
            if request is None:
                self._set("idle", "没有可继续的操作，正在更新当前连接状态。")
                return
            result = self._runner(request, binding)
            if not result["ok"]:
                if result["code"] == "connector_input_cancelled":
                    self._set("cancelled", "已取消本次操作。")
                else:
                    self._incomplete(result["code"])
                return
            self._completed(request)
        except ProductDataError as exc:
            self._set("failed", str(exc))
        except LifecycleError as exc:
            if exc.code in {"connector_uac_cancelled", "connector_input_cancelled"}:
                self._set("cancelled", "已取消本次操作。")
            else:
                self._reconcile(request)
        except (OSError, ValueError, TypeError, RuntimeError):
            self._reconcile(request)
        finally:
            self._public.end_authority_mutation()
            # Closing the UI does not undo the finite host operation.
            with suppress(PublicConnectivityProviderClosedError):
                self._public.request_refresh(full=True)
