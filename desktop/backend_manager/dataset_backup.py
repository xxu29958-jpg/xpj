"""UAC adapter for the installed complete-dataset backup owner."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import require_local_fixed_regular_file

_RESULT_FIELDS = {
    "schema",
    "backup_id",
    "generation",
    "dataset_id",
    "restore_epoch",
    "size_bytes",
}


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def run_installed_dataset_backup(
    layout: InstalledLayout,
    release: WindowsReleaseConfig,
) -> None:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise RuntimeControlError("Windows 系统目录不可用，未执行备份。")
    powershell = require_local_fixed_regular_file(
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
        label="Windows PowerShell 5.1",
    )
    script = require_local_fixed_regular_file(
        layout.install_dir / "installer" / "windows_dataset_backup.ps1",
        label="完整数据集备份 owner",
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
                "-BackupKind",
                "manual",
            ],
            cwd=layout.install_dir / "installer",
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=release.helper_watchdog_seconds("backup"),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RuntimeControlError("完整备份未能安全完成；原生诊断已抑制。") from exc
    if completed.returncode != 0 or completed.stderr.strip():
        raise RuntimeControlError("完整备份失败；原生诊断已抑制。")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeControlError("完整备份没有返回唯一结果。")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RuntimeControlError("完整备份结果无效。") from exc
    if (
        not isinstance(result, dict)
        or set(result) != _RESULT_FIELDS
        or result.get("schema") != "ticketbox-complete-dataset-backup-result-v1"
        or not _is_canonical_uuid(result.get("backup_id"))
        or result.get("generation") != f"ticketbox-backup-{result['backup_id']}"
        or not _is_canonical_uuid(result.get("dataset_id"))
        or isinstance(result.get("restore_epoch"), bool)
        or not isinstance(result.get("restore_epoch"), int)
        or result["restore_epoch"] < 0
        or isinstance(result.get("size_bytes"), bool)
        or not isinstance(result.get("size_bytes"), int)
        or result["size_bytes"] < 1
    ):
        raise RuntimeControlError("完整备份结果未通过闭合合同校验。")


__all__ = ["run_installed_dataset_backup"]
