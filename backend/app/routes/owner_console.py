"""Owner Console routes — local-only HTML admin UI.

All endpoints check that the request comes from the loopback address
(127.0.0.1 or ::1). Remote or Cloudflare-forwarded requests are rejected with
403. This is *not* a public admin backend.

Navigation:
    GET  /owner                     — dashboard / index
    GET  /owner/devices             — device list
    POST /owner/devices/{id}/revoke — revoke device
    POST /owner/devices/{id}/rename — rename device
    GET  /owner/pairing             — generate pairing code
    POST /owner/pairing             — create and display new code
    GET  /owner/upload-links        — upload link list
    POST /owner/upload-links        — create new upload link
    POST /owner/upload-links/{id}/rotate  — rotate key (one-shot reveal)
    POST /owner/upload-links/{id}/revoke  — revoke link
    GET  /owner/rule-applications   — read-only rule batch audit overview
    GET  /owner/diagnostics         — diagnostics page
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.fx_constants import CURRENCY_SYMBOLS, DEFAULT_HOME_CURRENCY_CODE
from app.network_boundary import require_owner_console_local
from app.services import owner_console_service as svc
from app.version import BACKEND_VERSION

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "owner"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _format_owner_datetime(value: object, tz: str = "Asia/Shanghai") -> str:
    """Format ISO-like datetimes for Owner Console tables.

    Accepts ``str`` (ISO-8601), ``datetime``, or anything falsy. Returns ``"—"``
    for falsy / unparseable input. Naive datetimes are assumed to be UTC; the
    output is rendered in the requested IANA timezone using ``YYYY-MM-DD HH:MM``
    so columns line up. Falls back to a simple ``[:16]`` slice if the runtime
    lacks the requested zone (e.g. minimal Windows base image without tzdata).
    """
    if not value:
        return "—"
    from datetime import datetime, timezone

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "—"
        try:
            # Python's fromisoformat handles "...+00:00"; replace trailing Z.
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw[:16].replace("T", " ")
    elif isinstance(value, datetime):
        dt = value
    else:
        return str(value)[:16].replace("T", " ")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        local = dt.astimezone(ZoneInfo(tz))
    except Exception:
        local = dt
    return local.strftime("%Y-%m-%d %H:%M")


templates.env.filters["owner_datetime"] = _format_owner_datetime

router = APIRouter(prefix="/owner", tags=["owner-console"])


def _require_local(request: Request) -> None:
    """Block non-loopback clients.

    v0.3-rc1-preflight: also reject public Host headers (Cloudflare Tunnel
    forwards to loopback so the TCP peer alone is insufficient).
    """
    require_owner_console_local(request)


LocalOnly = Depends(_require_local)


# ── helpers ─────────────────────────────────────────────────────────────────

_VALID_UI_THEMES = {"paper", "mono", "midnight"}


def _read_ui_theme(request: Request) -> str:
    raw = request.cookies.get("ui_theme")
    if raw in _VALID_UI_THEMES:
        return raw
    return "paper"


def _base(request: Request, db: Session) -> dict:
    """Common template context injected into every page."""
    cfg = get_settings()
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"
    home_currency = (cfg.fx_home_currency_code or DEFAULT_HOME_CURRENCY_CODE).upper()
    return {
        "backend_version": BACKEND_VERSION,
        "upload_dir_status": upload_status,
        "ui_theme": _read_ui_theme(request),
        "home_currency_code": home_currency,
        "home_currency_symbol": CURRENCY_SYMBOLS.get(home_currency, f"{home_currency} "),
    }


# ── index ────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def owner_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["ledger_health"] = svc.list_ledger_health(db)
    ctx["rule_audit"] = svc.get_rule_application_audit(db, ledger_id=None, limit=5)
    try:
        from app.services import windows_task_status_service as wts

        ctx["windows_tasks"] = wts.list_windows_tasks()
    except Exception:
        ctx["windows_tasks"] = []
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


@router.get("/rule-applications", response_class=HTMLResponse)
def owner_rule_applications(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    audit = svc.get_rule_application_audit(db, ledger_id=ledger_id, limit=20)
    ctx = _base(request, db)
    ctx["rule_audit"] = audit
    return templates.TemplateResponse(request=request, name="rule_applications.html", context=ctx)


# ── devices ──────────────────────────────────────────────────────────────────

@router.get("/devices", response_class=HTMLResponse)
def owner_devices(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    devices = svc.get_devices(db)
    ctx = _base(request, db)
    ctx["devices"] = devices
    return templates.TemplateResponse(request=request, name="devices.html", context=ctx)


@router.post("/devices/{public_id}/revoke", response_class=HTMLResponse)
def owner_revoke_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # Owner Console does not track which device "this" console session is from;
    # supply an empty string so the service rejects self-revoke only when the
    # admin uses the API directly with a token.
    svc.do_revoke_device(db, public_id, current_device_public_id="")
    return RedirectResponse(url="/owner/devices", status_code=303)


@router.post("/devices/{public_id}/rename", response_class=HTMLResponse)
def owner_rename_device(
    public_id: str,
    request: Request,
    device_name: str = Form(...),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_rename_device(db, public_id, device_name)
    return RedirectResponse(url="/owner/devices", status_code=303)


@router.post("/devices/{public_id}/delete", response_class=HTMLResponse)
def owner_delete_device(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_delete_device(db, public_id, current_device_public_id="")
    return RedirectResponse(url="/owner/devices", status_code=303)


# ── pairing ──────────────────────────────────────────────────────────────────

@router.get("/pairing", response_class=HTMLResponse)
def owner_pairing_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _base(request, db)
    ctx["pairing_result"] = None
    choices = svc.list_console_ledger_choices(db)
    default_id = svc.get_default_ledger_id(db)
    selected_id = default_id if default_id else (choices[0].ledger_id if choices else None)
    ctx["ledger_choices"] = choices
    ctx["ledger_id"] = selected_id
    ctx["selected_ledger_id"] = selected_id
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


@router.post("/pairing", response_class=HTMLResponse)
def owner_pairing_post(
    request: Request,
    ledger_id: str = Form(...),
    ttl_minutes: int = Form(default=15),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    choices = svc.list_console_ledger_choices(db)
    account_id = svc.get_owner_account_id(db)
    valid_ids = {c.ledger_id for c in choices}
    if not choices or account_id is None or ledger_id not in valid_ids:
        ctx = _base(request, db)
        ctx["pairing_result"] = None
        ctx["ledger_choices"] = choices
        ctx["ledger_id"] = None
        ctx["selected_ledger_id"] = ledger_id if ledger_id in valid_ids else None
        ctx["error"] = (
            "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
            if not choices
            else "请选择一个有权限的账本。"
        )
        return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)
    result = svc.do_create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)
    ctx = _base(request, db)
    ctx["pairing_result"] = result
    ctx["ledger_choices"] = choices
    ctx["ledger_id"] = ledger_id
    ctx["selected_ledger_id"] = ledger_id
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="pairing.html", context=ctx)


# ── upload links ─────────────────────────────────────────────────────────────

@router.get("/upload-links", response_class=HTMLResponse)
def owner_upload_links_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = None
    ctx["new_secret_full_url"] = None
    ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links", response_class=HTMLResponse)
def owner_upload_links_create(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ledger_id = svc.get_default_ledger_id(db)
    account_id = svc.get_owner_account_id(db)
    if ledger_id is None or account_id is None:
        ctx = _base(request, db)
        ctx["links"] = []
        ctx["new_secret"] = None
        ctx["new_secret_full_url"] = None
        ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
        ctx["error"] = "服务未初始化，请先运行 bootstrap_dev_owner.ps1。"
        return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)
    cfg = get_settings()
    tz = (cfg.ocr_default_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    _summary, secret = svc.do_create_upload_link(
        db, ledger_id=ledger_id, admin_account_id=account_id, default_timezone=tz
    )
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["new_secret_full_url"] = svc.compose_public_upload_url(secret)
    ctx["public_base_url_configured"] = bool(cfg.public_base_url)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/rotate", response_class=HTMLResponse)
def owner_upload_links_rotate(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _summary, secret = svc.do_rotate_upload_link(db, public_id)
    links = svc.get_upload_links(db)
    ctx = _base(request, db)
    ctx["links"] = links
    ctx["new_secret"] = secret
    ctx["new_secret_full_url"] = svc.compose_public_upload_url(secret)
    ctx["public_base_url_configured"] = bool(get_settings().public_base_url)
    ctx["error"] = None
    return templates.TemplateResponse(request=request, name="upload_links.html", context=ctx)


@router.post("/upload-links/{public_id}/revoke", response_class=HTMLResponse)
def owner_upload_links_revoke(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_revoke_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)


@router.post("/upload-links/{public_id}/delete", response_class=HTMLResponse)
def owner_upload_links_delete(
    public_id: str,
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    svc.do_delete_upload_link(db, public_id)
    return RedirectResponse(url="/owner/upload-links", status_code=303)


# ── diagnostics ──────────────────────────────────────────────────────────────

@router.get("/diagnostics", response_class=HTMLResponse)
def owner_diagnostics(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    vm = svc.get_index_vm(db)
    cfg = get_settings()
    ctx = _base(request, db)
    ctx.update(vm.__dict__)
    ctx["ocr_provider"] = cfg.ocr_provider
    ctx["ocr_auto_run"] = cfg.ocr_auto_run
    ctx["enable_http_bootstrap"] = cfg.enable_http_bootstrap
    ctx["max_upload_size_mb"] = cfg.max_upload_size_mb
    return templates.TemplateResponse(request=request, name="diagnostics.html", context=ctx)


# ── settings ─────────────────────────────────────────────────────────────────

from app.services import runtime_settings_service  # noqa: E402
from app.services import route_inspector_service  # noqa: E402


_SETTINGS_NAV = (
    {"slug": "", "label": "概览", "url": "/owner/settings"},
    {"slug": "public-base-url", "label": "公网域名", "url": "/owner/settings/public-base-url"},
    {"slug": "security", "label": "安全 / 边界", "url": "/owner/settings/security"},
    {"slug": "api", "label": "接口一览", "url": "/owner/settings/api"},
    {"slug": "about", "label": "关于", "url": "/owner/settings/about"},
)


def _settings_ctx(
    request: Request,
    db: Session,
    *,
    active: str = "",
    message: str | None = None,
    error: str | None = None,
) -> dict:
    ctx = _base(request, db)
    ctx["settings_view"] = runtime_settings_service.get_view()
    ctx["settings_nav"] = _SETTINGS_NAV
    ctx["settings_active"] = active
    ctx["message"] = message
    ctx["error"] = error
    return ctx


@router.get("/settings", response_class=HTMLResponse)
def owner_settings_index(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="")
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(
        request=request, name="settings/index.html", context=ctx
    )


@router.get("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_public_base_url_get(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="public-base-url")
    return templates.TemplateResponse(
        request=request, name="settings/public_base_url.html", context=ctx
    )


@router.post("/settings/public-base-url", response_class=HTMLResponse)
def owner_settings_set_public_base_url(
    request: Request,
    public_base_url: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    try:
        runtime_settings_service.update_public_base_url(public_base_url)
    except Exception as exc:  # surfaced to UI
        message = getattr(exc, "message", None) or "保存失败，请检查输入。"
        ctx = _settings_ctx(request, db, active="public-base-url", error=message)
        return templates.TemplateResponse(
            request=request, name="settings/public_base_url.html", context=ctx
        )
    ctx = _settings_ctx(
        request,
        db,
        active="public-base-url",
        message="已保存到 backend/.env，下一次创建上传链接即生效。",
    )
    return templates.TemplateResponse(
        request=request, name="settings/public_base_url.html", context=ctx
    )


@router.get("/settings/security", response_class=HTMLResponse)
def owner_settings_security(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="security")
    ctx["security_view"] = runtime_settings_service.get_security_view()
    return templates.TemplateResponse(
        request=request, name="settings/security.html", context=ctx
    )


@router.get("/settings/api", response_class=HTMLResponse)
def owner_settings_api(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="api")
    groups = route_inspector_service.list_route_groups(request.app)
    ctx["route_groups"] = groups
    ctx["route_total"] = route_inspector_service.count_routes(groups)
    return templates.TemplateResponse(
        request=request, name="settings/api.html", context=ctx
    )


@router.get("/settings/about", response_class=HTMLResponse)
def owner_settings_about(
    request: Request,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    ctx = _settings_ctx(request, db, active="about")
    ctx["about_view"] = runtime_settings_service.get_about_view()
    return templates.TemplateResponse(
        request=request, name="settings/about.html", context=ctx
    )


# ── backups ──────────────────────────────────────────────────────────────────

from app.services import backup_service  # noqa: E402  (local import to keep ordering tidy)
from app.services import migration_readiness_service  # noqa: E402


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
    except Exception as exc:  # AppError or unexpected I/O
        error = getattr(exc, "message", None) or "备份失败，请稍后再试。"
    entries = backup_service.list_backups()
    ctx = _base(request, db)
    ctx["backups"] = _backup_view(entries)
    ctx["latest"] = _backup_view([entries[0]])[0] if entries else None
    ctx["created_now"] = created
    ctx["error"] = error
    return templates.TemplateResponse(request=request, name="backups.html", context=ctx)


# ── v1.0 migration readiness ────────────────────────────────────────────────

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

