from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.errors import add_exception_handlers
from app.routes import auth, duplicates, expenses, maintenance, rules, settings, stats, uploads
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="小票夹 API",
    version="0.1.0",
    description="私人半自动记账系统后端。",
    lifespan=lifespan,
)

add_exception_handlers(app)

app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(expenses.router)
app.include_router(duplicates.router)
app.include_router(rules.router)
app.include_router(settings.router)
app.include_router(stats.router)
app.include_router(maintenance.router)


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse()
