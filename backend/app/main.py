from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from app.auth import get_current_app_context
from app.config import get_settings
from app.database import init_db
from app.errors import Utf8JSONResponse, add_exception_handlers
from app.middleware.cloudflare_access import cloudflare_access_guard
from app.middleware.csrf import csrf_loopback_form_guard
from app.middleware.logging import SanitizedLoggingMiddleware
from app.middleware.security_headers import security_headers
from app.middleware.static_owner_guard import static_owner_guard
from app.middleware.web_session import web_session_gate
from app.routes import admin as admin_routes
from app.routes import (
    auth,
    bill_split,
    bootstrap,
    budget_advisor,
    budgets,
    dashboard,
    debts,
    duplicates,
    exchange_rates,
    expenses,
    goals,
    imports,
    income_plans,
    insights,
    invitations,
    ledgers,
    maintenance,
    merchants,
    owner_console,
    owner_ledgers,
    recurring,
    repayment_drafts,
    reports,
    rules,
    settings,
    stats,
    tags,
    tasks,
    uploads,
    user_preferences,
    web_app,
    web_auth,
    web_bill_split,
    web_budget_advise,
    web_budgets,
    web_categories,
    web_dashboard,
    web_data_quality,
    web_debt_goals,
    web_debts,
    web_duplicates,
    web_expense_edit,
    web_expense_items,
    web_expense_splits,
    web_goals,
    web_import_export,
    web_income_plans,
    web_media,
    web_merchants,
    web_pending,
    web_receivables,
    web_recurring,
    web_repayment_drafts,
    web_reports,
    web_search,
    web_tags,
    web_tasks,
)
from app.routes import web_rules as web_rules_routes
from app.schemas import ErrorResponse, HealthResponse, StatusResponse
from app.services import backup_service
from app.services.app_meta_service import assert_binary_compatible_with_db
from app.services.background_task_service import (
    recover_orphaned_tasks,
    shutdown_executor,
)
from app.services.budget_advisor_audit_cleanup_scheduler import (
    start_budget_advisor_audit_cleanup_scheduler,
)
from app.services.device_cleanup_scheduler import start_device_cleanup_scheduler
from app.services.fx_rate_scheduler import start_fx_rate_scheduler
from app.services.learning_cleanup_scheduler import (
    start_learning_cleanup_scheduler,
)
from app.services.soft_delete_purge_scheduler import (
    start_soft_delete_purge_scheduler,
)
from app.tenants import AuthContext
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ERROR_RESPONSE_REF = {"$ref": "#/components/schemas/ErrorResponse"}
_logger = logging.getLogger(__name__)


def _assert_admin_api_gate_safe() -> None:
    """v1.1 Batch 1: if the owner explicitly opted into a public admin API
    (``ALLOW_PUBLIC_ADMIN_API=true``), refuse to boot unless Cloudflare
    Access is also wired up. The admin API does mutating ops with the
    admin token alone; without a real identity gate in front of it,
    anyone who can reach the public hostname can DOS or probe it.

    Loopback-only deployments (the default) skip this check.
    """

    cfg = get_settings()
    if not cfg.allow_public_admin_api:
        return
    missing = []
    if not cfg.cloudflare_access_required:
        missing.append("CLOUDFLARE_ACCESS_REQUIRED=true")
    if not cfg.cloudflare_access_team_domain:
        missing.append("CLOUDFLARE_ACCESS_TEAM_DOMAIN")
    if not cfg.cloudflare_access_aud:
        missing.append("CLOUDFLARE_ACCESS_AUD")
    if missing:
        raise RuntimeError(
            "ALLOW_PUBLIC_ADMIN_API=true requires Cloudflare Access to be "
            "configured. Missing: " + ", ".join(missing)
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _assert_admin_api_gate_safe()
    init_db()
    # ADR-0031 binary↔DB compatibility check (refuse to start a binary
    # older than the DB's schema_min_compatible).
    from app.database import SessionLocal as _SessionLocal
    from app.middleware.csrf import assert_csrf_signing_key_available, set_persisted_csrf_key
    from app.services.csrf_key_service import get_or_create_csrf_signing_key

    with _SessionLocal() as _db:
        assert_binary_compatible_with_db(_db)
        # ADR-0045: provision + stash the per-install CSRF signing key so the HMAC
        # key is a real per-install secret, never the public placeholder ADMIN_TOKEN
        # default. Auto-generated in app_meta on first boot (no operator step, no brick).
        set_persisted_csrf_key(get_or_create_csrf_signing_key(_db))
    assert_csrf_signing_key_available()
    # ADR-0049 §4 / P3b: when the Debt rollout is ON, backfill the member Debt for
    # any bill split accepted while the rollout was OFF — a deliberate self-heal that
    # kicks in once the operator flips the flag, a cheap no-op once reconciled, and a
    # no-op while OFF (an accepted split legitimately has no Debt in the closed period).
    from app.services.bill_split_service import reconcile_bill_split_debts_if_enabled

    reconcile_bill_split_debts_if_enabled()
    # ADR-0030 orphan recovery: tasks that were running or queued when
    # the previous process died are now phantoms — force-fail them.
    recover_orphaned_tasks()
    fx_scheduler = start_fx_rate_scheduler()
    # v1.2 ops: optional daily learning-table cleanup. Disabled by
    # default; opt in via LEARNING_CLEANUP_AUTO_ENABLED=true.
    learning_scheduler = start_learning_cleanup_scheduler()
    advisor_audit_scheduler = start_budget_advisor_audit_cleanup_scheduler()
    device_cleanup_scheduler = start_device_cleanup_scheduler()
    # ADR-0038 undo: optional periodic purge of soft-deleted rows past
    # retention. Disabled by default; opt in via SOFT_DELETE_PURGE_AUTO_ENABLED.
    soft_delete_purge_scheduler = start_soft_delete_purge_scheduler()
    try:
        yield
    finally:
        if fx_scheduler is not None:
            fx_scheduler.stop()
        if learning_scheduler is not None:
            learning_scheduler.stop()
        advisor_audit_scheduler.stop()
        device_cleanup_scheduler.stop()
        soft_delete_purge_scheduler.stop()
        shutdown_executor(wait=False)


app = FastAPI(
    title="小票夹 API",
    version=BACKEND_VERSION,
    description="私人半自动记账系统后端。",
    lifespan=lifespan,
    default_response_class=Utf8JSONResponse,
    docs_url="/docs" if get_settings().enable_api_docs else None,
    redoc_url="/redoc" if get_settings().enable_api_docs else None,
    openapi_url="/openapi.json" if get_settings().enable_api_docs else None,
)


def _project_error_response(existing: dict | None = None) -> dict:
    return {
        "description": (existing or {}).get("description") or "Structured project error response.",
        "content": {
            "application/json": {
                "schema": dict(_PROJECT_ERROR_RESPONSE_REF),
            },
        },
    }


def _uses_project_error_envelope(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/u/")


def _custom_openapi() -> dict:
    """OpenAPI document with project-level protocol fixes applied.

    The ADR-0042 ``Idempotency-Key`` header is marked ``required: true`` on
    outbox-routed mutate routes, and API/UploadLink error responses expose the
    real project ``ErrorResponse`` envelope instead of FastAPI's stock
    ``HTTPValidationError`` shape.

    The handlers declare the header as ``Header(default=None, ...)`` ON PURPOSE:
    a missing key is rejected inside the route body (``claim_idempotent_request``
    → 422 ``idempotency_key_required``) so the client gets the structured
    ``{"error": ..., "message": ...}`` contract and the three-tier idempotency
    error codes, instead of FastAPI's own generic validation-error body that a
    natively-required header would produce. But ``default=None`` makes FastAPI
    infer ``required: false``, which would tell a generated client the header is
    optional — callers would omit it and hit the runtime 422. The header IS
    contractually required, so we post-process the generated schema to say so
    without changing the runtime 422 body shape (ADR-0042 §4.4). The flip is
    safe blanket-wide: every ``Idempotency-Key`` parameter in this app belongs to
    an outbox-routed mutate route that runtime-requires it.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components["ErrorResponse"] = ErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    for path, path_item in schema.get("paths", {}).items():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                if (
                    parameter.get("in") == "header"
                    and parameter.get("name") == "Idempotency-Key"
                ):
                    parameter["required"] = True
            if _uses_project_error_envelope(path):
                responses = operation.setdefault("responses", {})
                responses["422"] = _project_error_response(responses.get("422"))
                responses["default"] = _project_error_response(responses.get("default"))
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi

add_exception_handlers(app)
app.add_middleware(SanitizedLoggingMiddleware)
# Starlette executes the most recently registered HTTP middleware first.
# Keep response hardening outermost, then Access, then our web session gate,
# then CSRF for the route body itself.
app.middleware("http")(csrf_loopback_form_guard)
app.middleware("http")(web_session_gate)
app.middleware("http")(static_owner_guard)
app.middleware("http")(cloudflare_access_guard)
app.middleware("http")(security_headers)

app.include_router(auth.router)
app.include_router(bootstrap.router)
app.include_router(uploads.router)
app.include_router(uploads.upload_link_router)
app.include_router(expenses.router)
app.include_router(exchange_rates.router)
app.include_router(duplicates.router)
app.include_router(ledgers.router)
app.include_router(invitations.router)
app.include_router(recurring.router)
app.include_router(budgets.router)
app.include_router(budget_advisor.router)
app.include_router(income_plans.router)
app.include_router(goals.router)
app.include_router(debts.router)
app.include_router(repayment_drafts.router)
app.include_router(dashboard.router)
app.include_router(rules.router)
app.include_router(settings.router)
app.include_router(user_preferences.router)
app.include_router(stats.router)
app.include_router(tags.router)
app.include_router(tasks.router)
app.include_router(bill_split.sender_router)
app.include_router(bill_split.inbox_router)
app.include_router(reports.router)
app.include_router(imports.router)
app.include_router(insights.router)
app.include_router(maintenance.router)
app.include_router(merchants.router)
app.include_router(admin_routes.router)
app.include_router(owner_console.router)
app.include_router(owner_ledgers.router)
# web_auth must come before web_app so its /web/auth/* routes win over any
# generic /web matcher (FastAPI registers first-mounted-first-matched).
app.include_router(web_auth.router)
app.include_router(web_app.router)
app.include_router(web_bill_split.router)
app.include_router(web_tasks.router)
app.include_router(web_dashboard.router)
app.include_router(web_expense_edit.router)
app.include_router(web_expense_items.router)
app.include_router(web_expense_splits.router)
app.include_router(web_media.router)
app.include_router(web_pending.router)
app.include_router(web_rules_routes.router)
app.include_router(web_budgets.router)
app.include_router(web_budget_advise.router)
app.include_router(web_income_plans.router)
app.include_router(web_reports.router)
app.include_router(web_goals.router)
app.include_router(web_search.router)
app.include_router(web_data_quality.router)
app.include_router(web_debts.router)
app.include_router(web_debt_goals.router)
app.include_router(web_repayment_drafts.router)
app.include_router(web_receivables.router)
app.include_router(web_categories.router)
app.include_router(web_duplicates.router)
app.include_router(web_import_export.router)
app.include_router(web_recurring.router)
app.include_router(web_merchants.router)
app.include_router(web_tags.router)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/api/health", response_model=StatusResponse, tags=["health"])
def health() -> StatusResponse:
    return StatusResponse()


@app.get("/api/status/private", response_model=HealthResponse, tags=["health"])
def private_status(_auth: AuthContext = Depends(get_current_app_context)) -> HealthResponse:
    cfg = get_settings()
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"
    # database_status: a static "ok". The PG-only store has no cheap
    # file-presence proxy, and a live connectivity probe is intentionally out
    # of scope (ENGINEERING_RULES §14 keeps the /health liveness+readiness
    # split off the v0.x roadmap). This public-tunnel endpoint never surfaces
    # host paths regardless.
    db_status = "ok"
    # 备份链健康(轴6 备份超龄通知数据源):复用 owner dashboard 的 backup_health()
    # ——48h stale 阈值留在服务端单源。只暴露时间戳/小时数/stale 布尔,不暴露
    # 文件名/目录(本端点过公网 tunnel,不得泄露本机路径)。
    try:
        backup = backup_service.backup_health()
        latest_backup_at = (
            backup.latest.created_at.astimezone(UTC).isoformat()
            if backup.latest is not None
            else None
        )
        backup_age_hours = backup.age_hours
        backup_stale = backup.stale
    except (OSError, RuntimeError):
        _logger.exception("private_status: backup_health failed")
        latest_backup_at = None
        backup_age_hours = None
        backup_stale = True
    return HealthResponse(
        status="ok",
        backend_version=BACKEND_VERSION,
        identity_schema=IDENTITY_SCHEMA_VERSION,
        database_status=db_status,
        upload_dir_status=upload_status,
        owner_console_status="available",
        latest_backup_at=latest_backup_at,
        backup_age_hours=backup_age_hours,
        backup_stale=backup_stale,
    )
