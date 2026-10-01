"""Inspect old unreferenced files, then dispose only that exact inspected set."""

import hashlib
import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.attachment_publication_lock import try_claim_orphan
from app.services.file_service import ALLOWED_EXTENSIONS, resolve_upload_path_for_tenant, upload_reference_for_path
from app.services.original_reference_queries import referenced_upload_paths
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID

CHUNK_SIZE = 32
RETRYABLE_OUTCOMES = frozenset({"busy", "failed"})


@dataclass(frozen=True)
class OrphanCleanupResult:
    dry_run: bool
    grace_hours: int
    scanned_files: int
    orphan_files: int
    deleted_files: int
    orphan_bytes: int
    deleted_bytes: int


def _plain_path(path: Path, root: Path) -> bool:
    """Reject symlinks and Windows junctions at every managed path component."""
    current = path
    while current != root:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            return False
        if current.parent == current:
            return False
        current = current.parent
    return True


def _raise_scan_error(error: OSError) -> None:
    raise error


def _managed_files(settings, tenant_id: str) -> Iterator[Path]:
    root = settings.upload_dir.resolve()
    roots = [root / tenant_id]
    if tenant_id == DEFAULT_TENANT_ID and root.is_dir():
        roots.extend(child for child in root.iterdir() if len(child.name) == 4 and child.name.isdigit())
    for scan_root in roots:
        if not scan_root.is_dir() or not _plain_path(scan_root, root):
            continue
        for directory, children, names in os.walk(scan_root, followlinks=False, onerror=_raise_scan_error):
            children[:] = [name for name in children if _plain_path(Path(directory) / name, root)]
            for name in names:
                path = Path(directory) / name
                if path.suffix.lower().removeprefix(".") in ALLOWED_EXTENSIONS and _plain_path(path, root):
                    yield path


def _snapshot(path: Path, reference: str) -> dict:
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("File changed during inspection")
    return {"reference": reference, "size": after.st_size, "mtime_ns": after.st_mtime_ns,
        "device": after.st_dev, "inode": after.st_ino, "sha256": digest,
        "modified_at": datetime.fromtimestamp(after.st_mtime, UTC).isoformat()}


def _inspect_chunk(db: Session, tenant_id: str, paths: list[tuple[str, Path]], result: dict, cutoff: datetime) -> None:
    claimed = []
    for reference, path in paths:
        if try_claim_orphan(db, reference):
            claimed.append((reference, path))
        else:
            result["busy_files"] += 1
    # A publisher may have committed between enumeration and our file claim.
    referenced = referenced_upload_paths(db, tenant_id)
    for reference, path in claimed:
        if reference in referenced:
            result["protected_files"] += 1
            continue
        try:
            candidate = _snapshot(path, reference)
        except OSError:
            result["unreadable_files"] += 1
            continue
        if datetime.fromtimestamp(candidate["mtime_ns"] / 1_000_000_000, UTC) > cutoff:
            continue
        result["_candidates"].append(candidate)
        result["candidate_files"] += 1
        result["candidate_bytes"] += candidate["size"]


def _candidate_path(path: Path, *, tenant_id: str, referenced: set[str], cutoff: datetime, result: dict) -> tuple[str, Path] | None:
    reference = upload_reference_for_path(path)
    if resolve_upload_path_for_tenant(reference, tenant_id) is None:
        return None
    result["scanned_files"] += 1
    if reference in referenced:
        result["protected_files"] += 1
        return None
    try:
        info = path.stat()
    except OSError:
        result["unreadable_files"] += 1
        return None
    return (reference, path) if datetime.fromtimestamp(info.st_mtime, UTC) <= cutoff else None


def inspect_orphans(db: Session, tenant_id: str, *, settings,
                    checkpoint: Callable[[dict], None]) -> dict:
    """Checkpoint inspection only; no file is deleted by this operation."""
    result = {"scanned_files": 0, "candidate_files": 0, "candidate_bytes": 0,
        "protected_files": 0, "busy_files": 0, "unreadable_files": 0,
        "grace_hours": max(settings.orphan_upload_grace_hours, 0), "_candidates": []}
    cutoff = now_utc() - timedelta(hours=result["grace_hours"])
    referenced = referenced_upload_paths(db, tenant_id)
    pending = []
    try:
        for path in _managed_files(settings, tenant_id):
            candidate = _candidate_path(path, tenant_id=tenant_id, referenced=referenced, cutoff=cutoff, result=result)
            if candidate is not None:
                pending.append(candidate)
            if result["scanned_files"] % CHUNK_SIZE == 0:
                _inspect_chunk(db, tenant_id, pending, result, cutoff)
                pending.clear()
                checkpoint(result)
    except OSError:
        result["unreadable_files"] += 1
    _inspect_chunk(db, tenant_id, pending, result, cutoff)
    checkpoint(result)
    return result


def _dispose_claimed(candidate: dict, *, tenant_id: str, referenced: set[str]) -> str:
    reference = candidate["reference"]
    path = resolve_upload_path_for_tenant(reference, tenant_id)
    if reference in referenced:
        return "referenced"
    if path is None or upload_reference_for_path(path) != reference:
        return "changed"
    try:
        if _snapshot(path, reference) != candidate:
            return "changed"
        path.unlink()
        return "deleted"
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "failed"


def dispose_chunk(db: Session, tenant_id: str, candidates: list[dict]) -> dict[str, str]:
    """Recheck identity and current references under nonblocking file claims."""
    outcomes = {}
    claimed = []
    for candidate in candidates:
        reference = candidate["reference"]
        if try_claim_orphan(db, reference):
            claimed.append(candidate)
        else:
            outcomes[reference] = "busy"
    referenced = referenced_upload_paths(db, tenant_id)
    for candidate in claimed:
        outcomes[candidate["reference"]] = _dispose_claimed(candidate, tenant_id=tenant_id, referenced=referenced)
    return outcomes


def disposal_summary(candidates: list[dict], outcomes: dict[str, str]) -> dict:
    counts = Counter(outcomes.values())
    return {"candidate_files": len(candidates), "processed_files": len(outcomes),
        "deleted_files": counts["deleted"], "deleted_bytes": sum(
            item["size"] for item in candidates if outcomes.get(item["reference"]) == "deleted"),
        "referenced_files": counts["referenced"], "changed_files": counts["changed"],
        "absent_files": counts["absent"], "busy_files": counts["busy"], "failed_files": counts["failed"],
        "_outcomes": outcomes}


def run_orphan_cleanup(db: Session, tenant_id: str, *, settings, dry_run: bool = True) -> OrphanCleanupResult:
    """Existing admin API uses the same reference, publication and disposal owner."""
    inspection = inspect_orphans(db, tenant_id, settings=settings, checkpoint=lambda _result: db.commit())
    candidates = inspection["_candidates"]
    outcomes = {}
    if not dry_run:
        for start in range(0, len(candidates), CHUNK_SIZE):
            outcomes.update(dispose_chunk(db, tenant_id, candidates[start:start + CHUNK_SIZE]))
            db.commit()
    disposed = disposal_summary(candidates, outcomes)
    return OrphanCleanupResult(dry_run, inspection["grace_hours"], inspection["scanned_files"],
        inspection["candidate_files"], disposed["deleted_files"], inspection["candidate_bytes"], disposed["deleted_bytes"])
