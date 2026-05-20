"""One-shot migration: move pre-v0.3 unscoped upload paths into ledger dirs.

Old uploads lived under ``uploads/YYYY/MM/file``. New uploads write under
``uploads/<ledger_id>/YYYY/MM/file``. This module rewrites legacy DB rows
and physically moves the files. It is called from owner tooling only, never
from a request path.
"""

from __future__ import annotations

from pathlib import Path
import secrets

from sqlalchemy import inspect, text

from app.config import BACKEND_ROOT
from app.database._core import SessionLocal, engine, settings
from app.database._validate import _validate_legacy_tenant_ids


__all__ = ["migrate_upload_paths_to_tenant_dirs"]


def _is_tenant_scoped_upload(path: Path, tenant_ids: set[str]) -> bool:
    try:
        first_part = path.relative_to(settings.upload_dir).parts[0]
    except (IndexError, ValueError):
        return False
    return first_part in tenant_ids


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    while True:
        candidate = path.with_name(f"{stem}-{secrets.token_hex(4)}{suffix}")
        if not candidate.exists():
            return candidate


def _move_legacy_upload_path(relative_path: str | None, tenant_id: str, tenant_ids: set[str]) -> str | None:
    if not relative_path:
        return relative_path

    source = (BACKEND_ROOT / relative_path).resolve()
    try:
        upload_relative = source.relative_to(settings.upload_dir)
    except ValueError:
        return relative_path
    if _is_tenant_scoped_upload(source, tenant_ids) or not source.is_file():
        return relative_path

    target = _unique_destination(settings.upload_dir / tenant_id / upload_relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.rename(target)
    except OSError:
        return relative_path
    return target.relative_to(BACKEND_ROOT).as_posix()


def migrate_upload_paths_to_tenant_dirs() -> None:
    from app.services.identity_service import ledger_ids
    from app.tenants import configured_tenants

    with engine.connect() as inspect_conn:
        has_ledgers = inspect(inspect_conn).has_table("ledgers")
    if has_ledgers:
        with SessionLocal() as db:
            tenant_ids = set(ledger_ids(db))
    else:
        tenant_ids = {tenant.id for tenant in configured_tenants()}
    _validate_legacy_tenant_ids(tenant_ids, source="ledgers")
    if not tenant_ids or not settings.upload_dir.exists():
        return

    with engine.begin() as connection:
        for tenant_id in tenant_ids:
            rows = connection.execute(
                text(
                    "SELECT id, image_path, thumbnail_path FROM expenses "
                    "WHERE tenant_id = :tenant_id "
                    "AND (image_path IS NOT NULL OR thumbnail_path IS NOT NULL)"
                ),
                {"tenant_id": tenant_id},
            ).mappings()
            for row in rows:
                image_path = _move_legacy_upload_path(row["image_path"], tenant_id, tenant_ids)
                thumbnail_path = _move_legacy_upload_path(row["thumbnail_path"], tenant_id, tenant_ids)
                if image_path != row["image_path"] or thumbnail_path != row["thumbnail_path"]:
                    connection.execute(
                        text(
                            "UPDATE expenses SET image_path = :image_path, thumbnail_path = :thumbnail_path "
                            "WHERE id = :id AND tenant_id = :tenant_id"
                        ),
                        {
                            "id": row["id"],
                            "tenant_id": tenant_id,
                            "image_path": image_path,
                            "thumbnail_path": thumbnail_path,
                        },
                    )
