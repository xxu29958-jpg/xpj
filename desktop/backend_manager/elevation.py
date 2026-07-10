"""Short-lived UAC broker for fixed installed-service actions."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend_manager.runtime import RuntimeControlError

ServiceAction = Literal["start", "stop", "restart"]

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_HELPER_TIMEOUT_MS = 300_000
_ERROR_CANCELLED = 1223

HELPER_EXIT_NOT_ELEVATED = 2
HELPER_EXIT_CONFIG = 3
HELPER_EXIT_TIMEOUT = 4
HELPER_EXIT_MISSING_SERVICE = 5
HELPER_EXIT_TRANSITION = 6
HELPER_EXIT_ACCESS = 7
HELPER_EXIT_OS = 8
_HELPER_WATCHDOG_SECONDS = 270.0

_HELPER_FAILURE_MESSAGES = {
    HELPER_EXIT_NOT_ELEVATED: "管理员授权未生效，服务没有变化。",
    HELPER_EXIT_CONFIG: "小票夹安装信息不可用，请修复或重新安装后重试。",
    HELPER_EXIT_TIMEOUT: "管理员服务助手已超时退出；Windows 服务可能仍在完成操作，请稍后刷新状态。",
    HELPER_EXIT_MISSING_SERVICE: "未找到小票夹 Windows 服务，请修复或重新安装。",
    HELPER_EXIT_TRANSITION: "Windows 服务未能进入目标状态，请刷新状态并查看服务日志。",
    HELPER_EXIT_ACCESS: "Windows 拒绝服务操作，请修复安装或服务权限后重试。",
    HELPER_EXIT_OS: "Windows 服务操作失败，请刷新状态并查看系统服务日志。",
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


def is_process_elevated() -> bool:
    if os.name != "nt":
        return False
    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    shell32.IsUserAnAdmin.argtypes = []
    shell32.IsUserAnAdmin.restype = ctypes.c_int
    return bool(shell32.IsUserAnAdmin())


def build_helper_command(action: ServiceAction) -> HelperCommand:
    executable = Path(sys.executable).resolve()
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        arguments = ("--elevated-service-action", action)
        working_dir = executable.parent
    else:
        arguments = ("-m", "backend_manager", "--elevated-service-action", action)
        working_dir = Path(__file__).resolve().parents[1]
    return HelperCommand(executable=executable, arguments=arguments, working_dir=working_dir)


def start_helper_watchdog(
    *,
    timeout_seconds: float = _HELPER_WATCHDOG_SECONDS,
    force_exit=os._exit,
) -> threading.Event:
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
        wait_result = kernel32.WaitForSingleObject(info.hProcess, _HELPER_TIMEOUT_MS)
        if wait_result == _WAIT_TIMEOUT:
            raise RuntimeControlError("管理员服务操作超过 300 秒仍未完成，请查看 Windows 服务状态。")
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

    def __init__(self, launcher=_launch_elevated) -> None:
        self._launcher = launcher

    def run(self, action: ServiceAction) -> None:
        exit_code = self._launcher(build_helper_command(action))
        if exit_code != 0:
            message = _HELPER_FAILURE_MESSAGES.get(
                exit_code,
                f"管理员服务操作失败（exit={exit_code}），请刷新服务状态后重试。",
            )
            raise RuntimeControlError(message)
