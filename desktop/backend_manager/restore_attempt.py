"""Per-user durable identity for one destructive restore attempt."""

from __future__ import annotations

import ctypes
import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Literal

from backend_manager import windows_user_security
from backend_manager.runtime import RuntimeControlError

_SCHEMA = "ticketbox-restore-attempt-v1"
_MAX_BYTES = 1024
_MOVEFILE_WRITE_THROUGH = 0x00000008
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_MAX_RETIRED_CLEANUP = 32
_RETIRED_NAME = re.compile(
    r"\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
    r"\.([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.retired\Z",
)
CleanupDisposition = Literal["clean", "cleanup_pending"]


def _move_windows_durable_no_replace(source: Path, target: Path) -> None:
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move_file.restype = ctypes.c_int
    if move_file(str(source), str(target), _MOVEFILE_WRITE_THROUGH):
        return
    error = ctypes.get_last_error()
    if error in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
        raise FileExistsError(error, "restore attempt already exists", str(target))
    raise ctypes.WinError(error)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _move_durable_no_replace(source: Path, target: Path) -> None:
    if os.name == "nt":
        _move_windows_durable_no_replace(source, target)
        return
    os.link(source, target)
    _fsync_directory(target.parent)
    source.unlink()
    _fsync_directory(target.parent)


def canonical_restore_attempt_id(value: str) -> str:
    if not isinstance(value, str):
        raise RuntimeControlError("完整恢复 attempt identity 无效。")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise RuntimeControlError("完整恢复 attempt identity 无效。") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise RuntimeControlError("完整恢复 attempt identity 无效。")
    return value


class RestoreAttemptStore:
    """Keep one attempt across UAC/result-channel loss until success is confirmed."""

    def __init__(self, root: Path) -> None:
        self._root = Path(os.path.abspath(root))

    def get_or_create(self, backup_generation: str) -> str:
        backup_id = _backup_id(backup_generation)
        self._secure_root()
        path = self._root / f"{backup_id}.json"
        if path.exists():
            return self._read(path, backup_generation)
        attempt_id = str(uuid.uuid4())
        payload = {
            "schema": _SCHEMA,
            "backup_generation": backup_generation,
            "attempt_id": attempt_id,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        temporary = self._root / f".{backup_id}.{attempt_id}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._secure_file(temporary)
            _move_durable_no_replace(temporary, path)
            self._secure_file(path)
        except FileExistsError:
            return self._read(path, backup_generation)
        finally:
            temporary.unlink(missing_ok=True)
        if self._read(path, backup_generation) != attempt_id:
            raise RuntimeControlError("无法验证完整恢复 attempt identity。")
        return attempt_id

    def retire_confirmed(self, backup_generation: str, attempt_id: str) -> CleanupDisposition:
        canonical_restore_attempt_id(attempt_id)
        path = self._root / f"{_backup_id(backup_generation)}.json"
        if self._read(path, backup_generation) != attempt_id:
            raise RuntimeControlError("完整恢复 attempt identity 已变化，拒绝清理。")
        retired = self._root / f".{_backup_id(backup_generation)}.{attempt_id}.retired"
        _move_durable_no_replace(path, retired)
        if path.exists():
            raise RuntimeControlError("完整恢复 attempt identity 未能清理。")
        return self.cleanup_retired()

    def cleanup_retired(self) -> CleanupDisposition:
        """Remove only bounded, exact-name tombstones without changing restore truth."""

        pending = False
        processed = 0
        try:
            self._secure_root()
            for path in self._root.iterdir():
                if _RETIRED_NAME.fullmatch(path.name) is None:
                    continue
                if processed >= _MAX_RETIRED_CLEANUP:
                    return "cleanup_pending"
                processed += 1
                try:
                    self._secure_file(path)
                    path.unlink(missing_ok=True)
                except (OSError, RuntimeControlError):
                    pending = True
        except (OSError, RuntimeControlError):
            return "cleanup_pending"
        return "cleanup_pending" if pending else "clean"

    def _read(self, path: Path, backup_generation: str) -> str:
        self._secure_root()
        self._secure_file(path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise RuntimeControlError("无法读取完整恢复 attempt identity。") from exc
        if not raw or len(raw) > _MAX_BYTES:
            raise RuntimeControlError("完整恢复 attempt identity 大小无效。")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeControlError("完整恢复 attempt identity 格式无效。") from exc
        if (
            not isinstance(payload, dict)
            or tuple(payload) != ("schema", "backup_generation", "attempt_id")
            or payload.get("schema") != _SCHEMA
            or payload.get("backup_generation") != backup_generation
        ):
            raise RuntimeControlError("完整恢复 attempt identity 绑定无效。")
        return canonical_restore_attempt_id(payload.get("attempt_id"))

    def _secure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if windows_user_security.is_reparse_point(self._root):
            raise RuntimeControlError("完整恢复 attempt 目录不能是重解析点。")
        if os.name == "nt":
            windows_user_security.set_exact_user_acl(self._root, directory=True)
        else:
            self._root.chmod(stat.S_IRWXU)

    @staticmethod
    def _secure_file(path: Path) -> None:
        if not path.is_file() or windows_user_security.is_reparse_point(path):
            raise RuntimeControlError("完整恢复 attempt 必须是普通文件。")
        if os.name == "nt":
            windows_user_security.set_exact_user_acl(path, directory=False)
        else:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _backup_id(backup_generation: str) -> str:
    prefix = "ticketbox-backup-"
    if not isinstance(backup_generation, str) or not backup_generation.startswith(prefix):
        raise RuntimeControlError("请选择一个明确、有效的完整备份 generation。")
    value = backup_generation.removeprefix(prefix)
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise RuntimeControlError("请选择一个明确、有效的完整备份 generation。") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise RuntimeControlError("请选择一个明确、有效的完整备份 generation。")
    return value


__all__ = ["CleanupDisposition", "RestoreAttemptStore", "canonical_restore_attempt_id"]
