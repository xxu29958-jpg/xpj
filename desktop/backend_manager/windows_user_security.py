"""Windows per-user roots, identity, and exact ACL helpers."""

from __future__ import annotations

import csv
import ctypes
import os
import re
import stat
import subprocess
from pathlib import Path

from backend_manager.runtime import RuntimeControlError

_CREATE_NO_WINDOW = 0x08000000
_CSIDL_LOCAL_APPDATA = 0x001C
_MB_OK = 0x00000000
_MB_ICONWARNING = 0x00000030
_NONCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


def show_elevated_manager_warning() -> None:
    if os.name != "nt":
        return
    user32 = ctypes.WinDLL("User32", use_last_error=True)
    user32.MessageBoxW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW(
        None,
        "小票夹管理器不能以管理员身份运行。请从 Windows 开始菜单正常打开；"
        "需要控制服务时会单独请求 UAC 授权。",
        "小票夹管理器",
        _MB_OK | _MB_ICONWARNING,
    )


def windows_system_directory() -> Path:
    if os.name != "nt":
        raise RuntimeControlError("Windows 服务提权操作只支持 Windows。")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel32.GetSystemDirectoryW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise RuntimeControlError("无法定位受信任的 Windows 系统目录。")
    return Path(buffer.value)


def local_app_data() -> Path:
    if os.name != "nt":
        raise RuntimeControlError("管理员结果通道只支持 Windows。")
    shell32 = ctypes.WinDLL("Shell32", use_last_error=True)
    buffer = ctypes.create_unicode_buffer(32768)
    result = shell32.SHGetFolderPathW(None, _CSIDL_LOCAL_APPDATA, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise RuntimeControlError(f"无法定位 LocalAppData（HRESULT=0x{result & 0xFFFFFFFF:08x}）。")
    return Path(os.path.abspath(buffer.value))


def current_user_sid() -> str:
    whoami = windows_system_directory() / "whoami.exe"
    try:
        result = subprocess.run(
            [str(whoami), "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
        row = next(csv.reader(result.stdout.splitlines()))
    except (OSError, subprocess.SubprocessError, StopIteration, csv.Error) as exc:
        raise RuntimeControlError("无法确定当前 Windows 用户 SID，拒绝创建管理员结果通道。") from exc
    if len(row) < 2 or not re.fullmatch(r"S-1-(?:[0-9]+-)+[0-9]+", row[1].strip(), re.IGNORECASE):
        raise RuntimeControlError("当前 Windows 用户 SID 格式无效，拒绝创建管理员结果通道。")
    return row[1].strip()


def is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & 0x400)


def require_local_fixed_regular_file(path: Path, *, label: str) -> Path:
    """Resolve one trusted executable without accepting network/reparse indirection."""
    if os.name != "nt":
        raise RuntimeControlError(f"{label}只支持 Windows。")
    try:
        canonical = Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeControlError(f"{label}路径无效。") from exc
    if not re.fullmatch(r"[A-Za-z]:", canonical.drive):
        raise RuntimeControlError(f"{label}必须位于本地固定磁盘。")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    if kernel32.GetDriveTypeW(f"{canonical.drive}\\") != 3:
        raise RuntimeControlError(f"{label}必须位于本地固定磁盘。")
    for component in (canonical, *canonical.parents):
        if component.exists() and is_reparse_point(component):
            raise RuntimeControlError(f"{label}路径包含重解析点。")
    try:
        resolved = canonical.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise RuntimeControlError(f"{label}不存在或无法读取。") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeControlError(f"{label}必须是单链接普通文件。")
    return resolved


def assert_helper_channel_path(path: Path, root: Path, nonce: str) -> None:
    if not _NONCE_PATTERN.fullmatch(nonce):
        raise RuntimeControlError("管理员结果通道 nonce 格式无效。")
    if not path.is_absolute() or not root.is_absolute():
        raise RuntimeControlError("管理员结果通道必须使用绝对路径。")
    canonical = Path(os.path.abspath(path))
    canonical_root = Path(os.path.abspath(root))
    if not re.fullmatch(r"[A-Za-z]:", canonical.drive) or canonical.drive.casefold() != canonical_root.drive.casefold():
        raise RuntimeControlError("管理员结果通道必须位于本地盘 caller profile。")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
        if kernel32.GetDriveTypeW(f"{canonical.drive}\\") != 3:
            raise RuntimeControlError("管理员结果通道必须位于本地固定磁盘。")
    if canonical.name != f"{nonce}.json":
        raise RuntimeControlError("管理员结果通道文件名与 nonce 不一致。")
    if os.path.normcase(str(canonical.parent)) != os.path.normcase(str(canonical_root)):
        raise RuntimeControlError("管理员结果通道不属于发起用户的 Ticketbox 目录。")
    for component in (canonical, canonical_root, *canonical_root.parents):
        if component.exists() and is_reparse_point(component):
            raise RuntimeControlError("管理员结果通道路径包含重解析点。")


def set_exact_user_acl(path: Path, *, directory: bool) -> None:
    sid = current_user_sid()
    grant_suffix = "(OI)(CI)F" if directory else "F"
    icacls = windows_system_directory() / "icacls.exe"
    grants = [f"*{sid}:{grant_suffix}", f"*S-1-5-18:{grant_suffix}", f"*S-1-5-32-544:{grant_suffix}"]
    try:
        result = subprocess.run(
            [str(icacls), str(path), "/inheritance:r", "/grant:r", *grants],
            check=False,
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeControlError("无法保护管理员结果通道 ACL。") from exc
    if result.returncode != 0:
        raise RuntimeControlError("无法保护管理员结果通道 ACL。")
