"""Copy and independently read back a stopped installation under the existing mutex."""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ticketbox_lifecycle.adapters.cold_copy import ColdCopyPlatform
from ticketbox_lifecycle.errors import LifecycleError


def cold_copy_backup_id(sha256: str) -> str:
    return str(uuid5(NAMESPACE_URL, "ticketbox-cold-copy:sha256:" + sha256))


def create_cold_copy(output: Path, platform: ColdCopyPlatform) -> dict[str, object]:
    platform.mutex.acquire()
    try:
        return create_cold_copy_locked(output, platform)
    finally:
        platform.mutex.release()


def create_cold_copy_locked(output: Path, platform: ColdCopyPlatform) -> dict[str, object]:
    source = platform.read_source()
    check_space = getattr(platform, "check_disk_space", None)
    if callable(check_space):
        check_space(output, source)
    with platform.create_archive(output) as target:
        result = platform.write_archive(target, source)
        target.seek(0)
        if platform.verify_archive(target) != result:
            raise LifecycleError("cold_corrupt", "completed copy could not be read back")
    return result
