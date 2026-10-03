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
from app.errors import AppError
from app.models import UploadLink, UploadLinkDailyUsage
from app.services.identity_service import hash_secret
from app.services.upload_link_throttle_service import (
    release_upload_bytes,
    reserve_upload_bytes,
    resolve_limits,
)
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


def _upload_link(upload_key: str) -> UploadLink:
    with SessionLocal() as db:
        return db.query(UploadLink).filter(
            UploadLink.token_hash == hash_secret(upload_key)
        ).one()


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


def test_daily_byte_budget_is_reserved_before_body_is_processed(
    identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "UPLOAD_LINK_DEFAULT_DAILY_BYTE_BUDGET", str(len(PNG_BYTES))
    )
    monkeypatch.setenv("UPLOAD_LINK_DEFAULT_PER_REMOTE_INTERVAL_SECONDS", "0")
    reset_settings_cache()
    reservation = None
    try:
        link = _upload_link(identity.upload_key)
        with SessionLocal() as first_db:
            first_link = first_db.get(UploadLink, link.id)
            assert first_link is not None
            reservation = reserve_upload_bytes(
                first_db,
                link=first_link,
                declared_content_length=len(PNG_BYTES),
                limits=resolve_limits(first_link),
            )

        with SessionLocal() as second_db:
            second_link = second_db.get(UploadLink, link.id)
            assert second_link is not None
            with pytest.raises(AppError) as exc:
                reserve_upload_bytes(
                    second_db,
                    link=second_link,
                    declared_content_length=1,
                    limits=resolve_limits(second_link),
                )
            assert exc.value.error == "upload_daily_quota_exhausted"
    finally:
        if reservation is not None:
            with SessionLocal() as cleanup_db:
                release_upload_bytes(cleanup_db, reservation=reservation)
        reset_settings_cache()


def test_link_list_remaining_budget_uses_current_utc_reservations(identity, quota_env, monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from app.services import upload_link_throttle_service as throttle
    from app.services.admin_service import _upload_links as links

    now = datetime(2026, 10, 4, 23, 59, tzinfo=UTC)
    monkeypatch.setattr(links, "now_utc", lambda: now)
    monkeypatch.setattr(throttle, "now_utc", lambda: now)
    link = _upload_link(identity.upload_key)
    with SessionLocal() as db:
        def remaining():
            rows = links.list_upload_links(db, ledger_ids={link.ledger_id})
            return next(row.daily_bytes_remaining for row in rows if row.public_id == link.public_id)

        assert remaining() == 1024
        reservation = reserve_upload_bytes(db, link=link, declared_content_length=600)
        assert remaining() == 424
        persisted = db.get(UploadLink, link.id)
        persisted.daily_byte_budget = 700
        db.commit()
        assert remaining() == 100
        persisted.daily_byte_budget = 0
        db.commit()
        assert remaining() is None
        persisted.daily_byte_budget = None
        db.commit()
        now += timedelta(minutes=2)
        assert remaining() == 1024
        now -= timedelta(minutes=2)
        assert remaining() == 424
        usage = db.query(UploadLinkDailyUsage).filter_by(upload_link_id=link.id).one()
        assert usage.bytes_total == 600 and usage.request_count == 0
        assert links.list_upload_links(db, ledger_ids=set()) == []
        release_upload_bytes(db, reservation=reservation)
        assert remaining() == 1024


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
