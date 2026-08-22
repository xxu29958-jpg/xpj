"""Filesystem adapter for byte-exact original attachment generations."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.errors import AppError
from app.services.dataset_backup_contract import OriginalArtifact, sha256_file
from app.services.path_entry_safety import is_link_or_reparse

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class OriginalReference:
    tenant_id: str
    storage_reference: str
    expected_sha256: str | None


def copy_complete_originals(
    *,
    upload_root: Path,
    destination: Path,
    references: tuple[OriginalReference, ...],
) -> tuple[OriginalArtifact, ...]:
    """Copy every original and prove all live DB references are represented.

    Thumbnail cache files are derived and omitted unless a database row wrongly
    references one as its original; that malformed-but-live reference is kept
    rather than silently losing user bytes.
    """

    root = _absolute_directory(upload_root)
    if destination.exists() or not destination.parent.is_dir():
        raise AppError("backup_incomplete", status_code=500)
    destination.mkdir()

    referenced: dict[str, list[OriginalReference]] = {}
    casefolded: dict[str, str] = {}
    for reference in references:
        relative = _reference_relative_path(reference.storage_reference)
        relative_text = relative.as_posix()
        collision_key = os.path.normcase(relative_text).casefold()
        previous = casefolded.get(collision_key)
        if previous is not None and previous != relative_text:
            raise AppError("backup_incomplete", status_code=500)
        casefolded[collision_key] = relative_text
        referenced.setdefault(relative_text, []).append(reference)

    artifacts: list[OriginalArtifact] = []
    for relative_text in sorted(referenced):
        relative = Path(relative_text)
        source = _bounded_file(root, relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, target, follow_symlinks=False)
            source_sha = sha256_file(source)
            target_sha = sha256_file(target)
            size = target.stat().st_size
        except OSError as exc:
            raise AppError("backup_incomplete", status_code=500) from exc
        if source_sha != target_sha or size < 1:
            raise AppError("backup_incomplete", status_code=500)
        bound_references = referenced.get(relative_text, [])
        for reference in bound_references:
            expected = (reference.expected_sha256 or "").casefold()
            if _SHA256.fullmatch(expected) is None or expected != target_sha:
                raise AppError("backup_incomplete", status_code=500)
        artifacts.append(
            OriginalArtifact(
                storage_key=f"originals/{relative.as_posix()}",
                size_bytes=int(size),
                sha256=target_sha,
                tenant_ids=tuple(sorted({item.tenant_id for item in bound_references})),
            )
        )
    return tuple(artifacts)


def _absolute_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise AppError("backup_incomplete", status_code=500)
    if is_link_or_reparse(path):
        raise AppError("backup_incomplete", status_code=500)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not resolved.is_dir() or is_link_or_reparse(resolved):
        raise AppError("backup_incomplete", status_code=500)
    return resolved


def _reference_relative_path(value: str) -> Path:
    text = str(value).replace("\\", "/")
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        raise AppError("backup_incomplete", status_code=500)
    parts = Path(text).parts
    if len(parts) < 2 or parts[0] != "uploads" or ".." in parts:
        raise AppError("backup_incomplete", status_code=500)
    relative = Path(*parts[1:])
    if not relative.parts:
        raise AppError("backup_incomplete", status_code=500)
    return relative


def _bounded_file(root: Path, relative: Path) -> Path:
    source = root / relative
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if is_link_or_reparse(source) or not resolved.is_file():
        raise AppError("backup_incomplete", status_code=500)
    return resolved
