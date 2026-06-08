"""Owner Console backup + v1.0 migration-readiness pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.owner_console._shared import LocalOnly, _base, templates
from app.services import backup_service, migration_readiness_service
from app.services import owner_console_service as owner_console

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


def _migration_readiness_view(
    report: migration_readiness_service.MigrationReadinessReport,
) -> dict:
    return {
        "target_version": report.target_version,
        "backend_version": report.backend_version,
        "identity_schema": report.identity_schema,
        "database_kind": report.database_kind,
        "dialect": report.dialect,
        "ready": report.ready,
        "backup_created": report.backup_created,
        "latest_backup": report.latest_backup,
        "latest_backup_kind": report.latest_backup_kind,
        "checks": [
            {
                "code": check.code,
                "status": check.status,
                "message": check.message,
                "badge_class": (
                    "badge-ok"
                    if check.status == "ok"
                    else "badge-warn"
                    if check.status == "warn"
                    else "badge-err"
                ),
            }
            for check in report.checks
        ],
    }


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


@router.get("/migration-readiness", response_class=HTMLResponse)
def owner_migration_readiness_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    report = migration_readiness_service.build_v1_migration_readiness_report(
        create_backup=False
    )
    ctx = _base(request, db)
    ctx["migration"] = _migration_readiness_view(report)
    ctx["created_now"] = None
    return templates.TemplateResponse(
        request=request, name="migration_readiness.html", context=ctx
    )


@router.post("/migration-readiness/pre-v1-backup", response_class=HTMLResponse)
def owner_migration_readiness_create_pre_v1_backup(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    report = migration_readiness_service.build_v1_migration_readiness_report(
        create_backup=True
    )
    ctx = _base(request, db)
    ctx["migration"] = _migration_readiness_view(report)
    ctx["created_now"] = report.backup_created
    return templates.TemplateResponse(
        request=request, name="migration_readiness.html", context=ctx
    )


@router.post("/migration-readiness/cut-over", response_class=HTMLResponse)
def owner_migration_cut_over(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """ADR-0031 cut-over: enqueue the v1_migration handler.

    The handler re-checks readiness, creates a rollback snapshot, then writes
    schema_version=1.0 / schema_min_compatible=1.0 to app_meta. The enqueue
    path is singleton-guarded so double-clicks reuse the active task instead
    of starting duplicate backups and cut-over writes.
    """
    from app.services import background_task_service, v1_migration_service

    owner_account_id = owner_console.get_owner_account_id(db)
    task, created = background_task_service.enqueue_or_get_active(
        db,
        task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
        initiator_account_id=owner_account_id,
        ledger_id=None,
    )
    report = migration_readiness_service.build_v1_migration_readiness_report(
        create_backup=False
    )
    ctx = _base(request, db)
    ctx["migration"] = _migration_readiness_view(report)
    ctx["created_now"] = None
    ctx["cut_over_task_public_id"] = task.public_id
    ctx["cut_over_task_reused"] = not created
    return templates.TemplateResponse(
        request=request, name="migration_readiness.html", context=ctx
    )
