from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db
from app.errors import Utf8JSONResponse, add_exception_handlers
from app.routes import auth, bootstrap, duplicates, expenses, maintenance, rules, settings, stats, uploads
from app.routes import admin as admin_routes
from app.routes import owner_console
from app.schemas import HealthResponse
from app.version import BACKEND_VERSION, IDENTITY_SCHEMA_VERSION
from app.middleware.logging import SanitizedLoggingMiddleware

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


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

app.include_router(auth.router)
app.include_router(bootstrap.router)
app.include_router(uploads.router)
app.include_router(uploads.upload_link_router)
app.include_router(expenses.router)
app.include_router(duplicates.router)
app.include_router(rules.router)
app.include_router(settings.router)
app.include_router(stats.router)
app.include_router(maintenance.router)
app.include_router(admin_routes.router)
app.include_router(owner_console.router)
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
