"""ADR-0045: per-install CSRF signing key (app_meta) + secret resolution.

Pins that the HMAC key is a real per-install secret — never the public placeholder
``ADMIN_TOKEN`` default — and that an operator-supplied real secret still wins.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import PLACEHOLDER_ADMIN_TOKEN, PLACEHOLDER_SECRETS, reset_settings_cache
from app.database import SessionLocal
from app.middleware import csrf as csrf_mw
from app.services import app_meta_service
from app.services.csrf_key_service import CSRF_SIGNING_KEY_META, get_or_create_csrf_signing_key


def test_get_or_create_csrf_signing_key_is_idempotent_and_non_placeholder(client: TestClient) -> None:
    with SessionLocal() as db:
        first = get_or_create_csrf_signing_key(db)
        second = get_or_create_csrf_signing_key(db)
    assert first == second  # stable across calls
    assert first  # non-empty real entropy
    assert first not in PLACEHOLDER_SECRETS  # not the public default
    with SessionLocal() as db:
        assert app_meta_service.get_value(db, CSRF_SIGNING_KEY_META) == first  # persisted


def test_csrf_secret_prefers_real_env_over_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    # Backward compat: an operator who deliberately set a real ADMIN_TOKEN keeps it.
    monkeypatch.setenv("ADMIN_TOKEN", "a-real-operator-secret")
    reset_settings_cache()
    saved_key = csrf_mw._persisted_csrf_key
    csrf_mw.set_persisted_csrf_key("persisted-key")
    try:
        assert csrf_mw._csrf_secret() == b"a-real-operator-secret"
    finally:
        csrf_mw._persisted_csrf_key = saved_key
        reset_settings_cache()


def test_csrf_secret_rejects_placeholder_and_falls_back_to_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    # The shipped public placeholder is rejected → the per-install persisted key wins.
    monkeypatch.setenv("ADMIN_TOKEN", PLACEHOLDER_ADMIN_TOKEN)
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "")
    monkeypatch.setenv("APP_TOKEN", "")
    reset_settings_cache()
    saved_key = csrf_mw._persisted_csrf_key
    csrf_mw.set_persisted_csrf_key("persisted-key")
    try:
        assert csrf_mw._csrf_secret() == b"persisted-key"
    finally:
        csrf_mw._persisted_csrf_key = saved_key
        reset_settings_cache()
