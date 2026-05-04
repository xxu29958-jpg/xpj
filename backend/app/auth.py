from __future__ import annotations

from hmac import compare_digest

from fastapi import Header

from app.config import get_settings
from app.errors import AppError


def _matches(actual: str | None, expected: str) -> bool:
    if not actual:
        return False
    return compare_digest(actual, expected)


def verify_upload_token(upload_token: str | None = Header(default=None, alias="Upload-Token")) -> None:
    settings = get_settings()
    if not _matches(upload_token, settings.upload_token):
        raise AppError("invalid_token", status_code=401)


def verify_app_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)

    token = authorization.removeprefix("Bearer ").strip()
    if not _matches(token, settings.app_token):
        raise AppError("invalid_token", status_code=401)


def verify_admin_token(authorization: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("invalid_token", status_code=401)

    token = authorization.removeprefix("Bearer ").strip()
    if not _matches(token, settings.admin_token):
        raise AppError("invalid_token", status_code=401)
