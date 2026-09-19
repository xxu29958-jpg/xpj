"""Request-scoped snapshots of the bytes identified by an original reference."""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

from app.errors import AppError
from app.services.file_service import resolve_protected_image
from app.services.stable_file_reader import hold_stable_file_for_read


@dataclass(frozen=True, slots=True)
class OriginalSnapshot:
    path: Path
    media_type: str
    sha256: str
    size_bytes: int
    verified: bool
    source_modified_at: float
    _cleanup: ExitStack = field(repr=False, compare=False)

    def close(self) -> None:
        self._cleanup.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def _copy_original(source: Path, target: Path) -> tuple[str, int, float]:
    digest = hashlib.sha256()
    size = 0
    with hold_stable_file_for_read(source) as original, target.open("xb") as snapshot:
        modified_at = os.fstat(original.fileno()).st_mtime
        while chunk := original.read(1024 * 1024):
            snapshot.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size, modified_at


def read_original_snapshot(
    *,
    relative_path: str | None,
    tenant_id: str,
    expected_sha256: str | None,
) -> OriginalSnapshot:
    """Copy once from a protected handle; consumers own and close the snapshot.

    The caller authorizes the Expense row and checks its deletion marker. Legacy
    absent/unusable digests permit an unverified read, never a metadata write.
    """
    source, media_type = resolve_protected_image(relative_path, tenant_id)
    expected = (expected_sha256 or "").strip().lower()
    known_digest = re.fullmatch(r"[0-9a-f]{64}", expected) is not None
    try:
        with ExitStack() as cleanup:
            directory = cleanup.enter_context(TemporaryDirectory(prefix="ticketbox-original-"))
            path = Path(directory) / f"original{source.suffix}"
            digest, size, modified_at = _copy_original(source, path)
            if known_digest and digest != expected:
                raise AppError("image_integrity_mismatch", status_code=409)
            return OriginalSnapshot(
                path=path, media_type=media_type, sha256=digest, size_bytes=size,
                verified=known_digest, source_modified_at=modified_at, _cleanup=cleanup.pop_all(),
            )
    except FileNotFoundError as exc:
        raise AppError("image_not_found", status_code=404) from exc
    except OSError as exc:
        raise AppError("image_read_failed", status_code=503) from exc
