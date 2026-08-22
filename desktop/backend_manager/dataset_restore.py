"""UAC adapter for the installed complete-dataset restore owner."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.restore_attempt import canonical_restore_attempt_id
from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import require_local_fixed_regular_file

_GENERATION = re.compile(
    r"ticketbox-backup-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_RESULT_FIELDS = {
    "schema",
    "restore_attempt_id",
    "backup_id",
    "dataset_id",
    "restore_epoch",
    "generation_operation_id",
    "result",
}
_UNKNOWN_RESULT = "完整恢复结果未知；请刷新服务和数据状态，确认后再决定是否重试。"
RestoreDisposition = Literal["current_published", "superseded"]


class RestoreSupersededError(RuntimeControlError):
    """The attempt completed, but a later Generation is CURRENT."""


def canonical_backup_generation(value: str) -> str:
    if not isinstance(value, str) or _GENERATION.fullmatch(value) is None:
        raise RuntimeControlError("请选择一个明确、有效的完整备份 generation。")
    backup_id = value.removeprefix("ticketbox-backup-")
    try:
        if str(uuid.UUID(backup_id)) != backup_id:
            raise ValueError
    except ValueError as exc:
        raise RuntimeControlError("请选择一个明确、有效的完整备份 generation。") from exc
    return value


def run_installed_dataset_restore(
    layout: InstalledLayout,
    release: WindowsReleaseConfig,
    backup_generation: str,
    restore_attempt_id: str,
) -> RestoreDisposition:
    generation = canonical_backup_generation(backup_generation)
    attempt_id = canonical_restore_attempt_id(restore_attempt_id)
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise RuntimeControlError("Windows 系统目录不可用，未执行恢复。")
    powershell = require_local_fixed_regular_file(
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
        label="Windows PowerShell 5.1",
    )
    script = require_local_fixed_regular_file(
        layout.install_dir / "installer" / "windows_dataset_restore.ps1",
        label="完整数据集恢复 owner",
    )
    environment = {
        name: os.environ[name]
        for name in ("SystemRoot", "WINDIR", "ComSpec", "TEMP", "TMP", "PATH", "PATHEXT")
        if name in os.environ
    }
    try:
        completed = subprocess.run(  # noqa: S603 - exact system executable and installed script
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-DataRoot",
                str(layout.data_root),
                "-BackupGeneration",
                generation,
                "-RestoreAttemptId",
                attempt_id,
            ],
            cwd=layout.install_dir / "installer",
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=release.helper_watchdog_seconds("restore"),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RuntimeControlError(_UNKNOWN_RESULT) from exc
    if completed.returncode != 0 or completed.stderr.strip():
        raise RuntimeControlError(_UNKNOWN_RESULT)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeControlError(_UNKNOWN_RESULT)
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RuntimeControlError(_UNKNOWN_RESULT) from exc
    if (
        not isinstance(result, dict)
        or set(result) != _RESULT_FIELDS
        or result.get("schema") != "ticketbox-complete-dataset-restore-result-v1"
        or result.get("result") not in {"current_published", "superseded"}
        or result.get("restore_attempt_id") != attempt_id
        or not _canonical_uuid(result.get("backup_id"))
        or result.get("backup_id") != generation.removeprefix("ticketbox-backup-")
        or not _canonical_uuid(result.get("dataset_id"))
        or not _canonical_uuid(result.get("generation_operation_id"))
        or isinstance(result.get("restore_epoch"), bool)
        or not isinstance(result.get("restore_epoch"), int)
        or result["restore_epoch"] < 1
    ):
        raise RuntimeControlError(_UNKNOWN_RESULT)
    return result["result"]


def _canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


__all__ = ["canonical_backup_generation", "run_installed_dataset_restore"]
