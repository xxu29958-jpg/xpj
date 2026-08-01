"""Owned cross-process sentinel used by every backup producer."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.errors import AppError
from app.services.time_service import now_utc

_logger = logging.getLogger(__name__)


@dataclass
class BackupJobLease:
    path: Path
    payload: bytes
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            persisted = self.path.read_bytes()
        except FileNotFoundError:
            return
        if persisted != self.payload:
            _logger.warning("backup lock ownership changed; refusing to remove it")
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def acquire_backup_job_lease(
    path: Path,
    *,
    stale: Callable[[Path], bool],
) -> BackupJobLease:
    payload = f"{os.getpid()}\n{now_utc().isoformat()}\n{uuid4().hex}\n".encode()
    while True:
        try:
            fd = os.open(
                str(path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            if stale(path):
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                continue
            raise AppError("backup_in_progress", status_code=409) from None
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        return BackupJobLease(path=path, payload=payload)
