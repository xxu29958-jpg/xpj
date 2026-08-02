"""Kernel-owned cross-process lease used by every backup producer."""

from __future__ import annotations

import errno
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.errors import AppError
from app.services.time_service import now_utc

_logger = logging.getLogger(__name__)


@dataclass
class BackupJobLease:
    path: Path
    payload: bytes
    stream: BinaryIO
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            _unlock_backup_file(self.stream)
        except OSError:
            _logger.warning("backup kernel lease unlock failed; closing its handle", exc_info=True)
        finally:
            self.stream.close()


class _BackupLeaseBusyError(Exception):
    pass


def _lock_backup_file(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise _BackupLeaseBusyError from exc
            raise
        return

    import fcntl

    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            raise _BackupLeaseBusyError from exc
        raise


def _unlock_backup_file(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def acquire_backup_job_lease(path: Path) -> BackupJobLease:
    payload = f"{os.getpid()}\n{now_utc().isoformat()}\n{uuid4().hex}\n".encode()
    fd = os.open(
        str(path),
        os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0),
        0o600,
    )
    stream = os.fdopen(fd, "r+b", buffering=0)
    try:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        _lock_backup_file(stream)
    except _BackupLeaseBusyError:
        stream.close()
        raise AppError("backup_in_progress", status_code=409) from None
    except OSError:
        stream.close()
        raise

    lease = BackupJobLease(path=path, payload=payload, stream=stream)
    try:
        stream.seek(0)
        stream.truncate()
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
    except OSError:
        lease.release()
        raise
    return lease
