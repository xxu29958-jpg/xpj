"""Copy and independently read back a stopped installation under the existing mutex."""

from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.adapters.cold_copy import ColdCopyPlatform
from ticketbox_lifecycle.errors import LifecycleError


def create_cold_copy(output: Path, platform: ColdCopyPlatform) -> dict[str, object]:
    platform.mutex.acquire()
    try:
        source = platform.read_source()
        with platform.create_archive(output) as target:
            result = platform.write_archive(target, source)
            target.seek(0)
            if platform.verify_archive(target) != result:
                raise LifecycleError("cold_corrupt", "completed copy could not be read back")
        return result
    finally:
        platform.mutex.release()
