"""UploadLink expiry policy boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.services.session_lifecycle_service import upload_link_expires_at


def test_new_upload_link_uses_runtime_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    issued_at = datetime(2026, 8, 21, tzinfo=UTC)
    monkeypatch.setenv("UPLOAD_LINK_TTL_DAYS", "7")
    get_settings.cache_clear()
    try:
        assert upload_link_expires_at(issued_at) == issued_at + timedelta(days=7)
    finally:
        get_settings.cache_clear()
