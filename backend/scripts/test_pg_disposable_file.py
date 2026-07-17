"""Serialized creation and fail-closed cleanup for derived test secrets."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_LOCK = threading.Lock()
_FILES: dict[str, Path] = {}
_CLEANUP_STARTED = False
_DELETE_RETRIES = 20
_DELETE_RETRY_SECONDS = 0.01


def _delete_file(path: Path) -> bool:
    for attempt in range(_DELETE_RETRIES):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        if not path.exists():
            return True
        if attempt + 1 < _DELETE_RETRIES:
            time.sleep(_DELETE_RETRY_SECONDS)
    return not path.exists()


@dataclass(frozen=True)
class DisposableTestFileReservation:
    token: str
    path: Path

    @contextlib.contextmanager
    def creation(self) -> Iterator[None]:
        """Serialize file creation against hard-exit cleanup."""

        with _LOCK:
            if _CLEANUP_STARTED:
                raise RuntimeError("Disposable test process cleanup has already started")
            if _FILES.get(self.token) != self.path:
                raise RuntimeError("Disposable test file reservation is no longer active")
            yield


@contextlib.contextmanager
def disposable_test_file_cleanup(
    path: Path,
) -> Iterator[DisposableTestFileReservation]:
    """Reserve a sensitive path and prove it absent before unregistering it."""

    if not path.is_absolute():
        raise ValueError("Disposable test cleanup path must be absolute")
    token = uuid4().hex
    with _LOCK:
        if _CLEANUP_STARTED:
            raise RuntimeError("Disposable test process cleanup has already started")
        _FILES[token] = path
    try:
        yield DisposableTestFileReservation(token, path)
    finally:
        if not _delete_file(path):
            raise RuntimeError(f"Could not remove disposable credential file: {path}")
        with _LOCK:
            _FILES.pop(token, None)


def _remove_disposable_test_files() -> tuple[Path, ...]:
    """Seal the registry, then remove every file created before the seal."""

    global _CLEANUP_STARTED

    with _LOCK:
        _CLEANUP_STARTED = True
        paths = tuple(reversed(tuple(_FILES.values())))
    return tuple(path for path in paths if not _delete_file(path))
