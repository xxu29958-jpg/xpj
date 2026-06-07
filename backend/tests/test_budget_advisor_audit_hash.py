"""ADR-0045 follow-up: the budget-advisor audit input-hash HMAC uses a per-install
key, not the public placeholder ADMIN_TOKEN default (the same degradation the CSRF
key had). The hash is never re-verified + the payload is never stored, so this is
consistency + key-separation, not a verified-signature change.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import PLACEHOLDER_ADMIN_TOKEN, PLACEHOLDER_SECRETS, reset_settings_cache
from app.database import SessionLocal
from app.services import app_meta_service
from app.services.budget_advisor_service._audit import (
    AUDIT_SIGNING_KEY_META,
    _audit_signing_secret,
    compute_input_hash,
)
from app.services.csrf_key_service import get_or_create_csrf_signing_key


def test_audit_secret_rejects_placeholder_persists_and_is_csrf_separated(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", PLACEHOLDER_ADMIN_TOKEN)
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "")
    monkeypatch.setenv("APP_TOKEN", "")
    reset_settings_cache()
    try:
        with SessionLocal() as db:
            first = _audit_signing_secret(db)
            second = _audit_signing_secret(db)
            csrf_key = get_or_create_csrf_signing_key(db)
            persisted = app_meta_service.get_value(db, AUDIT_SIGNING_KEY_META)
    finally:
        reset_settings_cache()
    assert first == second  # idempotent / stable
    assert first not in PLACEHOLDER_SECRETS  # not the public default
    assert first == persisted  # persisted in app_meta
    assert first != csrf_key  # key-separated from the CSRF signing key


def test_compute_input_hash_uses_audit_key_not_placeholder(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"b": 2, "a": 1}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")

    monkeypatch.setenv("ADMIN_TOKEN", PLACEHOLDER_ADMIN_TOKEN)
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", "")
    monkeypatch.setenv("APP_TOKEN", "")
    reset_settings_cache()
    try:
        with SessionLocal() as db:
            digest = compute_input_hash(db, payload)
            audit_key = _audit_signing_secret(db)
    finally:
        reset_settings_cache()

    expected = hmac.new(audit_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    placeholder_digest = hmac.new(PLACEHOLDER_ADMIN_TOKEN.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    assert digest == expected  # keyed by the per-install audit secret
    assert digest != placeholder_digest  # never the public placeholder constant


def test_compute_input_hash_prefers_real_env_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"x": 1}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    monkeypatch.setenv("ADMIN_TOKEN", "a-real-operator-secret")
    reset_settings_cache()
    try:
        with SessionLocal() as db:
            digest = compute_input_hash(db, payload)
    finally:
        reset_settings_cache()
    expected = hmac.new(b"a-real-operator-secret", raw, hashlib.sha256).hexdigest()
    assert digest == expected  # backward compat: a real operator secret wins
