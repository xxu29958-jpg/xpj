from __future__ import annotations

import os
import stat
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation


def durable_pending_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.pending")


def discard_durable_pending(path: Path) -> None:
    pending = durable_pending_path(path)
    try:
        observed = pending.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LifecycleViolation(
            "durable_pending_invalid",
            f"cannot inspect durable pending file: {pending.name}",
        ) from exc
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if (
        stat.S_ISLNK(observed.st_mode)
        or attributes & reparse_flag
        or not stat.S_ISREG(observed.st_mode)
    ):
        raise LifecycleViolation(
            "durable_pending_invalid",
            f"durable pending path is not a regular file: {pending.name}",
        )
    try:
        pending.unlink()
    except OSError as exc:
        raise LifecycleError(
            "durable_pending_cleanup_failed",
            f"cannot discard durable pending file: {pending.name}",
        ) from exc


def durable_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    discard_durable_pending(path)
    pending = durable_pending_path(path)
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
