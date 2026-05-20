from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.errors import Utf8JSONResponse, add_exception_handlers
from app.routes import auth, bootstrap, budgets, dashboard, duplicates, exchange_rates, expenses, goals, imports, insights, invitations, ledgers, maintenance, merchants, recurring, reports, rules, settings, stats, uploads, user_preferences
from app.routes import admin as admin_routes
from app.routes import owner_console
from app.routes import owner_ledgers
from app.routes import web_app
from app.routes import web_budgets
from app.routes import web_categories
from app.routes import web_data_quality
from app.routes import web_dashboard
from app.routes import web_duplicates
from app.routes import web_expense_edit
from app.routes import web_import_export
from app.routes import web_media
from app.routes import web_merchants
from app.routes import web_pending
from app.routes import web_recurring
from app.routes import web_goals
from app.routes import web_reports
from app.routes import web_rules as web_rules_routes
from app.routes import web_search
from app.routes import web_stats
from app.schemas import HealthResponse
from app.middleware.csrf import csrf_loopback_form_guard
from app.services.fx_rate_scheduler import start_fx_rate_scheduler
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION
from app.middleware.logging import SanitizedLoggingMiddleware

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    fx_scheduler = start_fx_rate_scheduler()
    try:
        yield
    finally:
        if fx_scheduler is not None:
            fx_scheduler.stop()


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

add_exception_handlers(app)
app.add_middleware(SanitizedLoggingMiddleware)
app.middleware("http")(csrf_loopback_form_guard)

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
app.include_router(goals.router)
app.include_router(dashboard.router)
app.include_router(rules.router)
app.include_router(settings.router)
app.include_router(user_preferences.router)
app.include_router(stats.router)
app.include_router(reports.router)
app.include_router(imports.router)
app.include_router(insights.router)
app.include_router(maintenance.router)
app.include_router(merchants.router)
app.include_router(admin_routes.router)
app.include_router(owner_console.router)
app.include_router(owner_ledgers.router)
app.include_router(web_app.router)
app.include_router(web_dashboard.router)
app.include_router(web_expense_edit.router)
app.include_router(web_media.router)
app.include_router(web_pending.router)
app.include_router(web_rules_routes.router)
app.include_router(web_stats.router)
app.include_router(web_budgets.router)
app.include_router(web_reports.router)
app.include_router(web_goals.router)
app.include_router(web_search.router)
app.include_router(web_data_quality.router)
app.include_router(web_categories.router)
app.include_router(web_duplicates.router)
app.include_router(web_import_export.router)
app.include_router(web_recurring.router)
app.include_router(web_merchants.router)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    cfg = get_settings()
    upload_status = "ok" if cfg.upload_dir.is_dir() else "missing"
    # database_status: SQLite file presence is the cheap proxy. We do NOT
    # surface the absolute filesystem path to avoid leaking host layout via
    # public health checks (Cloudflare Tunnel exposes this endpoint).
    db_status = "ok"
    if cfg.database_url.startswith("sqlite:///"):
        from pathlib import Path as _Path

        db_path = _Path(cfg.database_url[len("sqlite:///"):])
        db_status = "ok" if db_path.is_file() else "missing"
    return HealthResponse(
        status="ok",
        backend_version=BACKEND_VERSION,
        identity_schema=IDENTITY_SCHEMA_VERSION,
        database_status=db_status,
        upload_dir_status=upload_status,
        owner_console_status="available",
    )
