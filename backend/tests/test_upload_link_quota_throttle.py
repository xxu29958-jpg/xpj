"""v1.1 Batch 1: per-link daily quota + per-remote throttle for /u/{upload_key}.

These limits are off by default in the test env (tests fire bursts at
the upload link), so each test toggles the relevant env knob through
``monkeypatch`` and re-builds the cached settings.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.models import UploadLink, UploadLinkDailyUsage
from app.services.identity_service import hash_secret
from tests._infra.assets import PNG_BYTES


@pytest.fixture()
def quota_env(monkeypatch: pytest.MonkeyPatch):
    """Re-enable the per-link byte budget and a short per-remote interval."""

    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", "1024")
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "1")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _upload_link_id(upload_key: str) -> int:
    with SessionLocal() as db:
        link = db.query(UploadLink).filter(
            UploadLink.token_hash == hash_secret(upload_key)
        ).one()
        return link.id


def test_per_remote_interval_blocks_burst(
    client: TestClient, *, identity, quota_env
) -> None:
    first = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert first.status_code == 200

    second = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert second.status_code == 429
    assert second.json()["error"] == "upload_throttled"


def test_daily_byte_budget_exhausted_rejects_subsequent(
    client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Budget = PNG_BYTES length, interval off so we can hit twice in a row.
    monkeypatch.setenv(
        "UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", str(len(PNG_BYTES))
    )
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "0")
    reset_settings_cache()
    try:
        first = client.post(
            identity.upload_url_path,
            headers={**identity.upload_headers, "Content-Type": "image/png"},
            content=PNG_BYTES,
        )
        assert first.status_code == 200

        second = client.post(
            identity.upload_url_path,
            headers={**identity.upload_headers, "Content-Type": "image/png"},
            content=PNG_BYTES,
        )
        assert second.status_code == 429
        assert second.json()["error"] == "upload_daily_quota_exhausted"
    finally:
        reset_settings_cache()


def test_daily_usage_row_records_bytes_used(
    client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", str(10 * 1024 * 1024)
    )
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "0")
    reset_settings_cache()
    try:
        response = client.post(
            identity.upload_url_path,
            headers={**identity.upload_headers, "Content-Type": "image/png"},
            content=PNG_BYTES,
        )
        assert response.status_code == 200
        link_id = _upload_link_id(identity.upload_key)
        with SessionLocal() as db:
            usage = (
                db.query(UploadLinkDailyUsage)
                .filter(UploadLinkDailyUsage.upload_link_id == link_id)
                .one()
            )
            assert usage.bytes_total == len(PNG_BYTES)
            assert usage.request_count == 1
    finally:
        reset_settings_cache()


def test_content_length_pre_check_rejects_without_consuming_body(
    client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", "100")
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "0")
    reset_settings_cache()
    try:
        big = b"x" * 4096
        response = client.post(
            identity.upload_url_path,
            headers={
                **identity.upload_headers,
                "Content-Type": "image/png",
                "Content-Length": str(len(big)),
            },
            content=big,
        )
        assert response.status_code == 429
        assert response.json()["error"] == "upload_daily_quota_exhausted"
        # No usage row was created because we rejected before recording.
        link_id = _upload_link_id(identity.upload_key)
        with SessionLocal() as db:
            assert (
                db.query(UploadLinkDailyUsage)
                .filter(UploadLinkDailyUsage.upload_link_id == link_id)
                .count()
                == 0
            )
    finally:
        reset_settings_cache()
