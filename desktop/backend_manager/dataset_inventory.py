"""UAC adapter for the sanitized installed backup inventory projection."""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime

from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import (
    require_local_fixed_regular_file,
    trusted_windows_command_environment,
    windows_system_directory,
)

_ENTRY_FIELDS = {
    "generation",
    "backup_id",
    "dataset_id",
    "restore_epoch",
    "size_bytes",
    "created_at",
    "kind",
}
_PUBLIC_FIELDS = {"generation", "dataset_id", "restore_epoch", "size_bytes", "created_at"}


@dataclass(frozen=True)
class BackupInventoryItem:
    generation: str
    dataset_id: str
    restore_epoch: int
    size_bytes: int
    created_at: str

    def public_projection(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "dataset_id": self.dataset_id,
            "restore_epoch": self.restore_epoch,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }


def read_installed_dataset_inventory(
    layout: InstalledLayout,
    release: WindowsReleaseConfig,
) -> tuple[BackupInventoryItem, ...]:
    system_directory = windows_system_directory()
    powershell = require_local_fixed_regular_file(
        system_directory / "WindowsPowerShell" / "v1.0" / "powershell.exe",
        label="Windows PowerShell 5.1",
    )
    script = require_local_fixed_regular_file(
        layout.install_dir / "installer" / "windows_dataset_inventory.ps1",
        label="完整备份 inventory reader",
    )
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
            ],
            cwd=layout.install_dir / "installer",
            env=trusted_windows_command_environment(system_directory),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=release.helper_watchdog_seconds("inventory"),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RuntimeControlError("无法读取可信的完整备份列表。") from exc
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or completed.stderr.strip() or len(lines) != 1:
        raise RuntimeControlError("无法读取可信的完整备份列表。")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RuntimeControlError("完整备份列表无效。") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "generations"}:
        raise RuntimeControlError("完整备份列表合同无效。")
    generations = payload.get("generations")
    if payload.get("schema") != "ticketbox-manager-backup-inventory-v1" or not isinstance(generations, list):
        raise RuntimeControlError("完整备份列表合同无效。")
    if len(generations) > 3:
        raise RuntimeControlError("完整备份列表超过保留上限。")
    return tuple(_decode_item(item) for item in generations)


def _decode_item(value: object) -> BackupInventoryItem:
    if not isinstance(value, dict) or set(value) != _ENTRY_FIELDS:
        raise RuntimeControlError("完整备份列表条目无效。")
    backup_id = _uuid(value["backup_id"])
    dataset_id = _uuid(value["dataset_id"])
    generation = value["generation"]
    restore_epoch = value["restore_epoch"]
    size_bytes = value["size_bytes"]
    created_at = value["created_at"]
    try:
        if not isinstance(created_at, str):
            raise ValueError
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise RuntimeControlError("完整备份列表条目无效。") from exc
    if (
        generation != f"ticketbox-backup-{backup_id}"
        or value["kind"] != "manual"
        or not isinstance(restore_epoch, int)
        or isinstance(restore_epoch, bool)
        or restore_epoch < 0
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 1
        or len(created_at) != 27
        or not created_at.endswith("Z")
    ):
        raise RuntimeControlError("完整备份列表条目无效。")
    return BackupInventoryItem(generation, dataset_id, restore_epoch, size_bytes, created_at)


def decode_public_inventory(value: object) -> tuple[BackupInventoryItem, ...]:
    if not isinstance(value, list) or len(value) > 3:
        raise RuntimeControlError("完整备份列表合同无效。")
    items: list[BackupInventoryItem] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _PUBLIC_FIELDS:
            raise RuntimeControlError("完整备份列表条目无效。")
        generation = raw["generation"]
        if not isinstance(generation, str) or not generation.startswith("ticketbox-backup-"):
            raise RuntimeControlError("完整备份列表条目无效。")
        backup_id = _uuid(generation.removeprefix("ticketbox-backup-"))
        items.append(
            _decode_item(
                {
                    **raw,
                    "backup_id": backup_id,
                    "kind": "manual",
                }
            )
        )
    return tuple(items)


def _uuid(value: object) -> str:
    try:
        canonical = str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeControlError("完整备份列表条目无效。") from exc
    if canonical != value:
        raise RuntimeControlError("完整备份列表条目无效。")
    return canonical


__all__ = ["BackupInventoryItem", "decode_public_inventory", "read_installed_dataset_inventory"]
