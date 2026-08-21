"""Owner Console backup pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import backup_service

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / 1024 / 1024:.1f} MB"


def _backup_view(entries: list[backup_service.BackupEntry]) -> list[dict]:
    return [
        {
            "file_name": entry.file_name,
            "size_text": _format_size(entry.size_bytes),
            "created_at": entry.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": entry.kind,
            "dataset_id": entry.dataset_id,
            "restore_epoch": entry.restore_epoch,
        }
        for entry in entries
    ]


@router.get("/backups", response_class=HTMLResponse)
def owner_backups_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    entries = backup_service.list_backups()
    ctx = _base(request, db)
    ctx["backups"] = _backup_view(entries)
    ctx["latest"] = _backup_view([entries[0]])[0] if entries else None
    ctx["backup_dir"] = backup_service.backup_directory_label()
    ctx["backup_health"] = backup_service.backup_health()
    return templates.TemplateResponse(request=request, name="backups.html", context=ctx)
