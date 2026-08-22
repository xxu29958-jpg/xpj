"""Short-lived UAC broker for fixed installed-service actions."""

from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import subprocess
import threading
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from backend_manager import windows_user_security
from backend_manager.helper_channel import (
    channel_file_identity,
    open_exclusive_channel,
    require_sid,
    validate_exact_file_security,
)
from backend_manager.installation import WindowsReleaseConfig
from backend_manager.runtime import RestoreOutcome, RuntimeControlError

if TYPE_CHECKING:
    from backend_manager.dataset_inventory import BackupInventoryItem

ServiceAction = Literal["start", "stop", "restart", "backup", "restore", "inventory"]

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_CANCELLED = 1223
_MAX_RESULT_BYTES = 16 * 1024
_MAX_DIAGNOSTIC_CHARS = 800
_RESULT_SCHEMA = "ticketbox-manager-helper-result-v2"
_FILE_ID_PATTERN = re.compile(r"[0-9a-f]+:[0-9a-f]+\Z")
HELPER_EXIT_NOT_ELEVATED = 2
HELPER_EXIT_CONFIG = 3
HELPER_EXIT_TIMEOUT = 4
HELPER_EXIT_MISSING_SERVICE = 5
HELPER_EXIT_TRANSITION = 6
HELPER_EXIT_ACCESS = 7
HELPER_EXIT_OS = 8
HELPER_EXIT_LIFECYCLE_BUSY = 9
HELPER_EXIT_RESTORE_SUPERSEDED = 10

_HELPER_FAILURE_MESSAGES = {
    HELPER_EXIT_NOT_ELEVATED: "管理员授权未生效，服务没有变化。",
    HELPER_EXIT_CONFIG: "小票夹安装信息不可用，请修复或重新安装后重试。",
    HELPER_EXIT_TIMEOUT: "管理员服务助手已超时退出；Windows 服务可能仍在完成操作，请稍后刷新状态。",
    HELPER_EXIT_MISSING_SERVICE: "未找到小票夹 Windows 服务，请修复或重新安装。",
    HELPER_EXIT_TRANSITION: "Windows 服务未能进入目标状态，请刷新状态后重试。",
    HELPER_EXIT_ACCESS: "Windows 拒绝服务操作，请修复安装或服务权限后重试。",
    HELPER_EXIT_OS: "Windows 服务操作失败，请刷新状态并查看 Windows 服务事件。",
    HELPER_EXIT_LIFECYCLE_BUSY: "小票夹正在安装、升级或卸载，请等待完成后再操作服务。",
    HELPER_EXIT_RESTORE_SUPERSEDED: "此前恢复已被后续数据 generation 取代，请重新确认后再发起恢复。",
}


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


@dataclass(frozen=True)
class HelperCommand:
    executable: Path
    arguments: tuple[str, ...]
    working_dir: Path
    wait_timeout_ms: int


@dataclass(frozen=True)
class HelperResult:
    exit_code: int
    diagnostic: str
    payload: object


@dataclass(frozen=True)
class HelperResultChannel:
    path: Path
    root: Path
    nonce: str
    action: ServiceAction
    owner_sid: str | None = None
    file_identity: str | None = None

    def read(self, process_exit_code: int) -> HelperResult | None:
        try:
            payload = _read_channel_payload(
                self.path,
                self.root,
                self.nonce,
                self.action,
                self.owner_sid,
                self.file_identity,
                pending=False,
            )
        except RuntimeControlError:
            return None
        expected_keys = {"schema", "root", "nonce", "action", "file_identity", "exit_code", "diagnostic", "payload"}
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            return None
        if (
            payload.get("schema") != _RESULT_SCHEMA
            or payload.get("root") != str(Path(os.path.abspath(self.root)))
            or not secrets.compare_digest(str(payload.get("nonce", "")), self.nonce)
            or payload.get("action") != self.action
            or payload.get("file_identity") != self.file_identity
            or payload.get("exit_code") != process_exit_code
        ):
            return None
        diagnostic = payload.get("diagnostic")
        if not isinstance(diagnostic, str) or not diagnostic or len(diagnostic) > _MAX_DIAGNOSTIC_CHARS:
            return None
        return HelperResult(exit_code=process_exit_code, diagnostic=diagnostic, payload=payload["payload"])


def is_process_elevated() -> bool:
    if os.name != "nt":
        return False
    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes = []
    shell32.IsUserAnAdmin.restype = ctypes.c_int
    return bool(shell32.IsUserAnAdmin())


def _read_channel_payload(
    path: Path,
    root: Path,
    nonce: str,
    action: ServiceAction,
    owner_sid: str | None,
    file_identity: str | None,
    *,
    pending: bool,
) -> dict:
    windows_user_security.assert_helper_channel_path(path, root, nonce)
    try:
        with open_exclusive_channel(path) as stream:
            actual_identity = channel_file_identity(stream)
            if file_identity is not None and actual_identity != file_identity:
                raise RuntimeControlError("管理员结果通道文件身份已变化。")
            if owner_sid is not None:
                validate_exact_file_security(root, require_sid(owner_sid), directory=True)
                validate_exact_file_security(path, require_sid(owner_sid))
            raw = stream.read(_MAX_RESULT_BYTES + 1)
    except OSError as exc:
        raise RuntimeControlError("无法读取管理员结果通道。") from exc
    if len(raw) > _MAX_RESULT_BYTES:
        raise RuntimeControlError("管理员结果通道超过大小上限。")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeControlError("管理员结果通道 JSON 无效。") from exc
    expected = (
        {"schema", "root", "nonce", "action", "state", "owner_sid", "file_identity"}
        if pending
        else {
            "schema",
            "root",
            "nonce",
            "action",
            "file_identity",
            "exit_code",
            "diagnostic",
            "payload",
        }
    )
    if not isinstance(payload, dict) or set(payload) != expected:
        raise RuntimeControlError("管理员结果通道字段不符合精确契约。")
    if (
        payload.get("schema") != _RESULT_SCHEMA
        or payload.get("root") != str(Path(os.path.abspath(root)))
        or payload.get("action") != action
    ):
        raise RuntimeControlError("管理员结果通道 schema 或 action 不匹配。")
    if not secrets.compare_digest(str(payload.get("nonce", "")), nonce):
        raise RuntimeControlError("管理员结果通道 nonce 不匹配。")
    if pending and (
        payload.get("state") != "pending"
        or payload.get("owner_sid") != owner_sid
        or payload.get("file_identity") != file_identity
    ):
        raise RuntimeControlError("管理员结果通道 pending 绑定不匹配。")
    return payload


def validate_helper_result_channel(
    path: Path,
    root: Path,
    nonce: str,
    action: ServiceAction,
    owner_sid: str,
    file_identity: str,
) -> None:
    if not _FILE_ID_PATTERN.fullmatch(file_identity):
        raise RuntimeControlError("管理员结果通道文件身份格式无效。")
    _read_channel_payload(path, root, nonce, action, owner_sid, file_identity, pending=True)


@contextmanager
def create_helper_result_channel(action: ServiceAction):
    nonce = secrets.token_urlsafe(32)
    root = Path(os.path.abspath(windows_user_security.local_app_data() / "Ticketbox" / "helper-results"))
    owner_sid = windows_user_security.current_user_sid()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{nonce}.json"
    windows_user_security.assert_helper_channel_path(path, root, nonce)
    windows_user_security.set_exact_user_acl(root, directory=True)
    try:
        with path.open("x", encoding="utf-8"):
            pass
        windows_user_security.set_exact_user_acl(path, directory=False)
        validate_exact_file_security(root, owner_sid, directory=True)
        validate_exact_file_security(path, owner_sid)
        with open_exclusive_channel(path) as stream:
            file_identity = channel_file_identity(stream)
            pending = {
                "schema": _RESULT_SCHEMA,
                "root": str(root),
                "nonce": nonce,
                "action": action,
                "state": "pending",
                "owner_sid": owner_sid,
                "file_identity": file_identity,
            }
            stream.write(json.dumps(pending, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        validate_helper_result_channel(path, root, nonce, action, owner_sid, file_identity)
        yield HelperResultChannel(
            path=path,
            root=root,
            nonce=nonce,
            action=action,
            owner_sid=owner_sid,
            file_identity=file_identity,
        )
    finally:
        with suppress(OSError):
            path.unlink(missing_ok=True)


def sanitize_helper_diagnostic(message: str, fallback: str) -> str:
    """Return only the caller-owned public copy; raw elevated errors stay private."""
    del message
    return " ".join(fallback.replace("\x00", " ").split())[:_MAX_DIAGNOSTIC_CHARS]


def write_helper_result(
    path: Path,
    root: Path,
    nonce: str,
    action: ServiceAction,
    owner_sid: str,
    file_identity: str,
    exit_code: int,
    diagnostic: str,
    payload: object,
) -> None:
    public_fallback = "操作已完成。" if exit_code == 0 else _HELPER_FAILURE_MESSAGES.get(exit_code, "操作失败。")
    payload = {
        "schema": _RESULT_SCHEMA,
        "root": str(Path(os.path.abspath(root))),
        "nonce": nonce,
        "action": action,
        "file_identity": file_identity,
        "exit_code": exit_code,
        "diagnostic": sanitize_helper_diagnostic(diagnostic, public_fallback),
        "payload": payload,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise RuntimeControlError("管理员结果超过通道上限。")
    windows_user_security.assert_helper_channel_path(path, root, nonce)
    if not _FILE_ID_PATTERN.fullmatch(file_identity):
        raise RuntimeControlError("管理员结果通道文件身份格式无效。")
    try:
        with open_exclusive_channel(path) as stream:
            if channel_file_identity(stream) != file_identity:
                raise RuntimeControlError("管理员结果通道文件身份已变化。")
            validate_exact_file_security(root, require_sid(owner_sid), directory=True)
            validate_exact_file_security(path, require_sid(owner_sid))
            raw = stream.read(_MAX_RESULT_BYTES + 1)
            if len(raw) > _MAX_RESULT_BYTES:
                raise RuntimeControlError("管理员结果通道超过大小上限。")
            try:
                pending = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeControlError("管理员结果通道 JSON 无效。") from exc
            expected = {"schema", "root", "nonce", "action", "state", "owner_sid", "file_identity"}
            if not isinstance(pending, dict) or set(pending) != expected:
                raise RuntimeControlError("管理员结果通道字段不符合精确契约。")
            if (
                pending.get("schema") != _RESULT_SCHEMA
                or pending.get("root") != str(Path(os.path.abspath(root)))
                or pending.get("action") != action
                or pending.get("state") != "pending"
                or pending.get("owner_sid") != owner_sid
                or pending.get("file_identity") != file_identity
                or not secrets.compare_digest(str(pending.get("nonce", "")), nonce)
            ):
                raise RuntimeControlError("管理员结果通道 pending 绑定不匹配。")
            stream.seek(0)
            stream.write(encoded.encode("utf-8"))
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise RuntimeControlError("无法写入管理员结果通道。") from exc


def _build_helper_command(
    action: ServiceAction,
    channel: HelperResultChannel,
    wait_timeout_ms: int,
    *,
    helper_executable: Path,
    request_arguments: tuple[str, ...],
) -> HelperCommand:
    expected_parent = Path(os.path.abspath(helper_executable.parent))
    if helper_executable.name.casefold() != "ticketbox-manager.exe" or expected_parent.name.casefold() != "manager":
        raise RuntimeControlError("正式服务操作只能使用安装目录中的 ticketbox-manager.exe。")
    executable = windows_user_security.require_local_fixed_regular_file(
        helper_executable,
        label="正式 Manager 服务助手",
    )
    if os.path.normcase(str(executable.parent)) != os.path.normcase(str(expected_parent)):
        raise RuntimeControlError("正式 Manager 服务助手解析后离开了登记安装目录。")
    helper_args = (
        "--elevated-service-action",
        action,
        *request_arguments,
        "--helper-result-path",
        str(channel.path),
        "--helper-result-root",
        str(channel.root),
        "--helper-result-nonce",
        channel.nonce,
        "--helper-channel-owner-sid",
        require_sid(channel.owner_sid or ""),
        "--helper-channel-file-id",
        channel.file_identity or "",
    )
    return HelperCommand(
        executable=executable,
        arguments=helper_args,
        working_dir=executable.parent,
        wait_timeout_ms=wait_timeout_ms,
    )


def build_helper_command(
    action: ServiceAction,
    channel: HelperResultChannel,
    wait_timeout_ms: int,
    *,
    helper_executable: Path,
) -> HelperCommand:
    if action == "restore":
        raise RuntimeControlError("restore helper 缺少明确 backup generation。")
    return _build_helper_command(
        action,
        channel,
        wait_timeout_ms,
        helper_executable=helper_executable,
        request_arguments=(),
    )


def build_restore_helper_command(
    backup_generation: str,
    restore_attempt_id: str,
    channel: HelperResultChannel,
    wait_timeout_ms: int,
    *,
    helper_executable: Path,
) -> HelperCommand:
    from backend_manager.dataset_restore import canonical_backup_generation
    from backend_manager.restore_attempt import canonical_restore_attempt_id

    generation = canonical_backup_generation(backup_generation)
    attempt_id = canonical_restore_attempt_id(restore_attempt_id)
    return _build_helper_command(
        "restore",
        channel,
        wait_timeout_ms,
        helper_executable=helper_executable,
        request_arguments=(
            "--backup-generation",
            generation,
            "--restore-attempt-id",
            attempt_id,
        ),
    )


def start_helper_watchdog(*, timeout_seconds: float, force_exit=os._exit) -> threading.Event:
    """Force the elevated helper itself to end before the parent wait expires."""
    cancelled = threading.Event()

    def watch() -> None:
        if not cancelled.wait(timeout_seconds):
            force_exit(HELPER_EXIT_TIMEOUT)

    threading.Thread(target=watch, daemon=True).start()
    return cancelled


def _launch_elevated(command: HelperCommand) -> int:
    if os.name != "nt":
        raise RuntimeControlError("Windows 服务提权操作只支持 Windows。")

    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(command.executable)
    info.lpParameters = subprocess.list2cmdline(command.arguments)
    info.lpDirectory = str(command.working_dir)
    info.nShow = _SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            raise RuntimeControlError("已取消管理员授权，服务没有变化。")
        raise RuntimeControlError(f"无法启动管理员服务助手（Windows error={error}）。")
    try:
        wait_result = kernel32.WaitForSingleObject(info.hProcess, command.wait_timeout_ms)
        if wait_result == _WAIT_TIMEOUT:
            seconds = command.wait_timeout_ms / 1000
            raise RuntimeControlError(f"管理员服务操作超过 {seconds:g} 秒仍未完成，请刷新 Windows 服务状态。")
        if wait_result != _WAIT_OBJECT_0:
            raise RuntimeControlError(f"等待管理员服务助手失败（Windows wait={wait_result}）。")
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise RuntimeControlError(f"无法读取管理员服务助手结果（Windows error={ctypes.get_last_error()}）。")
        return int(exit_code.value)
    finally:
        if info.hProcess:
            kernel32.CloseHandle(info.hProcess)


class ElevatedServiceActionRunner:
    """Ask Windows for consent, run one fixed helper action, then drop elevation."""

    def __init__(
        self,
        release: WindowsReleaseConfig,
        helper_executable: Path,
        launcher=_launch_elevated,
        channel_factory=create_helper_result_channel,
    ) -> None:
        self._release = release
        self._helper_executable = helper_executable
        self._launcher = launcher
        self._channel_factory = channel_factory

    def run(self, action: ServiceAction) -> None:
        with self._channel_factory(action) as channel:
            command = build_helper_command(
                action,
                channel,
                self._release.helper_parent_timeout_ms(action),
                helper_executable=self._helper_executable,
            )
            exit_code = self._launcher(command)
            result = channel.read(exit_code)
        if result is None:
            if exit_code in _HELPER_FAILURE_MESSAGES:
                raise RuntimeControlError(_HELPER_FAILURE_MESSAGES[exit_code])
            raise RuntimeControlError("管理员服务助手未返回可信结果；请刷新服务状态后重试。")
        if exit_code != 0:
            message = result.diagnostic or _HELPER_FAILURE_MESSAGES.get(
                exit_code,
                f"管理员服务操作失败（exit={exit_code}），请刷新服务状态后重试。",
            )
            raise RuntimeControlError(message)

    def restore(self, backup_generation: str) -> RestoreOutcome:
        from backend_manager.restore_attempt import RestoreAttemptStore
        from backend_manager.windows_user_security import local_app_data

        action: ServiceAction = "restore"
        attempt_store = RestoreAttemptStore(local_app_data() / "Ticketbox" / "restore-attempts")
        restore_attempt_id = attempt_store.get_or_create(backup_generation)
        with self._channel_factory(action) as channel:
            command = build_restore_helper_command(
                backup_generation,
                restore_attempt_id,
                channel,
                self._release.helper_parent_timeout_ms(action),
                helper_executable=self._helper_executable,
            )
            exit_code = self._launcher(command)
            result = channel.read(exit_code)
        if result is None:
            if exit_code in _HELPER_FAILURE_MESSAGES:
                raise RuntimeControlError(_HELPER_FAILURE_MESSAGES[exit_code])
            raise RuntimeControlError("管理员服务助手未返回可信结果；请刷新服务状态后重试。")
        if exit_code == HELPER_EXIT_RESTORE_SUPERSEDED:
            retirement = attempt_store.retire_confirmed(backup_generation, restore_attempt_id)
            message = result.diagnostic or _HELPER_FAILURE_MESSAGES[HELPER_EXIT_RESTORE_SUPERSEDED]
            if retirement == "cleanup_pending":
                message += " 本地恢复身份清理待下次维护重试。"
            raise RuntimeControlError(message)
        if exit_code != 0:
            message = result.diagnostic or _HELPER_FAILURE_MESSAGES.get(
                exit_code,
                f"管理员服务操作失败（exit={exit_code}），请刷新服务状态后重试。",
            )
            raise RuntimeControlError(message)
        retirement = attempt_store.retire_confirmed(backup_generation, restore_attempt_id)
        return RestoreOutcome(cleanup_pending=retirement == "cleanup_pending")

    def backup_inventory(self) -> tuple[BackupInventoryItem, ...]:
        from backend_manager.dataset_inventory import decode_public_inventory

        action: ServiceAction = "inventory"
        with self._channel_factory(action) as channel:
            command = build_helper_command(
                action,
                channel,
                self._release.helper_parent_timeout_ms(action),
                helper_executable=self._helper_executable,
            )
            exit_code = self._launcher(command)
            result = channel.read(exit_code)
        if result is None or exit_code != 0:
            raise RuntimeControlError("无法读取可信的完整备份列表。")
        return decode_public_inventory(result.payload)
