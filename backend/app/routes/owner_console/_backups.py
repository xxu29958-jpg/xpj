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
    ctx["created_now"] = None
    ctx["error"] = None
    ctx["backup_dir"] = backup_service.backup_directory_label()
    return templates.TemplateResponse(request=request, name="backups.html", context=ctx)


@router.post("/backups", response_class=HTMLResponse)
def owner_backups_create(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    error: str | None = None
    created: dict | None = None
    try:
        entry = backup_service.create_manual_backup()
        created = _backup_view([entry])[0]
    except Exception as exc:  # noqa: BLE001 — AppError or unexpected I/O surfaces to UI
        error = getattr(exc, "message", None) or "备份失败，请稍后再试。"
    entries = backup_service.list_backups()
    ctx = _base(request, db)
    ctx["backups"] = _backup_view(entries)
    ctx["latest"] = _backup_view([entries[0]])[0] if entries else None
    ctx["created_now"] = created
    ctx["error"] = error
    ctx["backup_dir"] = backup_service.backup_directory_label()
    return templates.TemplateResponse(request=request, name="backups.html", context=ctx)
