"""ADR-0045: per-install CSRF signing key persisted in ``app_meta``.

The CSRF HMAC key must be a per-install secret, NOT the shipped placeholder
``ADMIN_TOKEN`` default (``replace-with-random-admin-token``), which is public in
the repository. When no real operator secret is configured, the key is a random
value generated once and stored in the ``app_meta`` KV table — auto-provisioned on
first boot and stable across restarts (so a healthy DB always satisfies the
startup guard; nothing for the operator to set, no brick).
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.services import app_meta_service

CSRF_SIGNING_KEY_META = "csrf_signing_key"


def get_or_create_csrf_signing_key(db: Session) -> str:
    """Return the persisted CSRF signing key, generating + storing one on first
    call. Idempotent: a second call returns the same stored value. Single-process
    home deployment provisions this at startup before serving requests, so there
    is no first-boot write race."""
    existing = app_meta_service.get_value(db, CSRF_SIGNING_KEY_META)
    if existing:
        return existing
    key = secrets.token_urlsafe(32)
    app_meta_service.set_value(db, CSRF_SIGNING_KEY_META, key)
    return key
