"""Top-level health, error, and auth-check envelopes used across surfaces."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "AuthCheckResponse",
    "ErrorResponse",
    "HealthResponse",
    "StatusResponse",
]


class ErrorResponse(BaseModel):
    error: str
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    backend_version: str | None = None
    identity_schema: str | None = None
    database_status: str | None = None
    upload_dir_status: str | None = None
    owner_console_status: str | None = None


class AuthCheckResponse(BaseModel):
    status: str = "ok"
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str
    scope: str


class StatusResponse(BaseModel):
    status: str = "ok"
