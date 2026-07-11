"""Per-user Manager ownership and the protected instance proof."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from backend_manager import windows_user_security
from backend_manager.helper_channel import open_exclusive_channel, validate_exact_file_security
from backend_manager.runtime import RuntimeControlError

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x00000080
_PROOF_SCHEMA = "ticketbox-manager-instance-proof-v1"
_PROOF_LIMIT = 1024
_PROOF_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")


class _OwnershipHandle(Protocol):
    owner: bool

    def try_acquire(self) -> bool: ...
    def close(self) -> None: ...


class _WindowsMutex:
    def __init__(self, handle: int, *, owner: bool) -> None:
        self._handle = handle
        self.owner = owner

    def close(self) -> None:
        if not self._handle:
            return
        kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        if self.owner:
            kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = 0

    def try_acquire(self) -> bool:
        if self.owner:
            return True
        kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        result = kernel32.WaitForSingleObject(self._handle, 0)
        if result not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            return False
        self.owner = True
        return True


class _PosixFileLock:
    def __init__(self, stream: BinaryIO, *, owner: bool) -> None:
        self._stream = stream
        self.owner = owner

    def close(self) -> None:
        import fcntl

        if self.owner:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()

    def try_acquire(self) -> bool:
        if self.owner:
            return True
        import fcntl

        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        self.owner = True
        return True


@dataclass
class InstanceRegistration:
    secret: str
    port: int | None


@dataclass
class ManagerInstance:
    is_owner: bool
    secret: str | None
    port: int | None
    root: Path
    proof_path: Path
    _ownership: _OwnershipHandle

    def read_secret(self) -> str | None:
        if self.is_owner:
            return self.secret
        registration = self.read_registration()
        return registration.secret if registration is not None else None

    def read_registration(self) -> InstanceRegistration | None:
        if self.is_owner and self.secret is not None:
            return InstanceRegistration(self.secret, self.port)
        with suppress(OSError, RuntimeControlError, UnicodeError, json.JSONDecodeError):
            return _read_instance_proof(self.root, self.proof_path)
        return None

    def close(self) -> None:
        if self.is_owner:
            with suppress(OSError):
                self.proof_path.unlink(missing_ok=True)
        self._ownership.close()

    def try_take_ownership(self) -> bool:
        if self.is_owner:
            return True
        if not self._ownership.try_acquire():
            return False
        self.is_owner = True
        self.secret = secrets.token_urlsafe(32)
        self.port = None
        _write_instance_proof(self.root, self.proof_path, _current_user_sid(), self.secret, None)
        return True

    def publish_port(self, port: int) -> None:
        if not self.is_owner or self.secret is None or not 1 <= port <= 65535:
            raise RuntimeControlError("无法发布管理器实例端口。")
        _write_instance_proof(self.root, self.proof_path, _current_user_sid(), self.secret, port)
        self.port = port


def _current_user_sid() -> str:
    if os.name == "nt":
        return windows_user_security.current_user_sid()
    return f"uid-{os.getuid()}"


def _instance_root() -> Path:
    if os.name == "nt":
        return windows_user_security.local_app_data() / "Ticketbox" / "manager-instance"
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "ticketbox" / "manager-instance"


def _windows_mutex(user_sid: str, *, namespace: str = "TicketboxManager") -> _WindowsMutex:
    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", ctypes.c_ulong),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", ctypes.c_int),
        ]

    advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{user_sid})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,
        ctypes.byref(descriptor),
        None,
    ):
        raise RuntimeControlError("无法建立小票夹管理器单实例安全描述符。")
    try:
        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        mutex_id = hashlib.sha256(user_sid.casefold().encode("utf-8")).hexdigest()[:32]
        handle = kernel32.CreateMutexW(ctypes.byref(attributes), True, f"Global\\{namespace}-{mutex_id}")
        error = ctypes.get_last_error()
        if not handle:
            raise RuntimeControlError(f"无法取得小票夹管理器单实例所有权（Windows error={error}）。")
        return _WindowsMutex(handle, owner=error != _ERROR_ALREADY_EXISTS)
    finally:
        kernel32.LocalFree(descriptor)


def _posix_lock(root: Path) -> _PosixFileLock:
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "instance.lock").open("a+b")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return _PosixFileLock(stream, owner=False)
    return _PosixFileLock(stream, owner=True)


def _claim_os_ownership(user_sid: str, root: Path) -> _OwnershipHandle:
    return _windows_mutex(user_sid) if os.name == "nt" else _posix_lock(root)


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return True


def _require_fixed_local_root(root: Path) -> None:
    if not root.is_absolute():
        raise RuntimeControlError("管理器实例证明目录必须使用绝对路径。")
    if os.name == "nt":
        canonical = Path(os.path.abspath(root))
        if not re.fullmatch(r"[A-Za-z]:", canonical.drive):
            raise RuntimeControlError("管理器实例证明目录必须位于本地固定磁盘。")
        kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
        if kernel32.GetDriveTypeW(f"{canonical.drive}\\") != 3:
            raise RuntimeControlError("管理器实例证明目录必须位于本地固定磁盘。")
    for component in (root, *root.parents):
        if component.exists() and _is_reparse_point(component):
            raise RuntimeControlError("管理器实例证明目录包含重解析点。")


def _validate_proof_file(root: Path, path: Path, user_sid: str) -> None:
    _require_fixed_local_root(root)
    if os.path.normcase(str(Path(os.path.abspath(path.parent)))) != os.path.normcase(
        str(Path(os.path.abspath(root))),
    ):
        raise RuntimeControlError("管理器实例证明文件不属于当前用户目录。")
    validate_exact_file_security(root, user_sid, directory=True)
    validate_exact_file_security(path, user_sid)


def _read_instance_proof(root: Path, path: Path) -> InstanceRegistration:
    user_sid = _current_user_sid()
    _validate_proof_file(root, path, user_sid)
    with open_exclusive_channel(path) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeControlError("管理器实例证明必须是单链接普通文件。")
        raw = stream.read(_PROOF_LIMIT + 1)
    if len(raw) > _PROOF_LIMIT:
        raise RuntimeControlError("管理器实例证明超过大小上限。")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema", "owner_sid", "secret", "port"}:
        raise RuntimeControlError("管理器实例证明字段不符合精确契约。")
    secret = payload.get("secret")
    port = payload.get("port")
    if (
        payload.get("schema") != _PROOF_SCHEMA
        or payload.get("owner_sid") != user_sid
        or not isinstance(secret, str)
        or not _PROOF_PATTERN.fullmatch(secret)
        or (
            port is not None
            and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535)
        )
    ):
        raise RuntimeControlError("管理器实例证明身份不匹配。")
    return InstanceRegistration(secret, port)


def _write_instance_proof(root: Path, path: Path, user_sid: str, secret: str, port: int | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _require_fixed_local_root(root)
    if os.name == "nt":
        windows_user_security.set_exact_user_acl(root, directory=True)
        validate_exact_file_security(root, user_sid, directory=True)
    if path.exists():
        if _is_reparse_point(path):
            raise RuntimeControlError("管理器实例证明文件不能是重解析点。")
        path.unlink()
    payload = {"schema": _PROOF_SCHEMA, "owner_sid": user_sid, "secret": secret, "port": port}
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "nt":
        windows_user_security.set_exact_user_acl(path, directory=False)
    _validate_proof_file(root, path, user_sid)
    if _read_instance_proof(root, path) != InstanceRegistration(secret, port):
        raise RuntimeControlError("无法验证管理器实例证明。")


@contextmanager
def claim_manager_instance() -> Iterator[ManagerInstance]:
    """Claim this user's Manager slot, or expose the current owner's protected proof."""
    user_sid = _current_user_sid()
    root = Path(os.path.abspath(_instance_root()))
    proof_path = root / "instance.json"
    ownership = _claim_os_ownership(user_sid, root)
    secret: str | None = None
    port: int | None = None
    instance: ManagerInstance | None = None
    try:
        if ownership.owner:
            secret = secrets.token_urlsafe(32)
            _write_instance_proof(root, proof_path, user_sid, secret, port)
        instance = ManagerInstance(ownership.owner, secret, port, root, proof_path, ownership)
        yield instance
    except BaseException:
        raise
    finally:
        if instance is not None:
            instance.close()
        else:
            if ownership.owner:
                with suppress(OSError):
                    proof_path.unlink(missing_ok=True)
            ownership.close()
