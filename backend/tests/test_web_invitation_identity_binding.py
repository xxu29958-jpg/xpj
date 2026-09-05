"""A native invitation confirmation keeps the identity the person reviewed."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, Invitation, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.test_family_ledger_permissions import _mint_foreign_ledger_invitation

pytestmark = pytest.mark.real_db


def _hidden_fields(html: str) -> dict[str, str]:
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html))


def test_old_invitation_confirmation_refuses_a_different_logged_in_account(client, identity) -> None:
    first_session = mint_session(client, identity=identity)
    target_ledger, target_invite = _mint_foreign_ledger_invitation()
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, first_session, domain=PUBLIC_HOST, path="/")
    origin = {"Origin": f"https://{PUBLIC_HOST}"}
    entry = browser.get("/web/auth/join")
    preview = browser.post(
        "/web/auth/join/preview",
        data={**_hidden_fields(entry.text), "invite_token": target_invite},
        headers=origin,
    )
    assert preview.status_code == 200, preview.text
    original_form = _hidden_fields(preview.text)

    # The same browser's second tab logs out and connects as a different person.
    logged_out = browser.post(
        "/web/auth/logout", data=original_form, headers=origin, follow_redirects=False,
    )
    assert logged_out.status_code == 303
    _, other_invite = _mint_foreign_ledger_invitation()
    next_preview = browser.post(
        "/web/auth/join/preview",
        data={**original_form, "invite_token": other_invite},
        headers=origin,
    )
    assert next_preview.status_code == 200, next_preview.text
    other_join = browser.post(
        "/web/auth/join/accept",
        data={**_hidden_fields(next_preview.text), "account_name": "另一位家人"},
        headers=origin,
        follow_redirects=False,
    )
    assert other_join.status_code == 303, other_join.text

    refused = browser.post(
        "/web/auth/join/accept", data=original_form, headers=origin, follow_redirects=False,
    )
    assert refused.status_code == 409, refused.text
    assert "另一位家人" in refused.text
    with SessionLocal() as db:
        current_token = db.scalar(select(AuthToken).where(
            AuthToken.token_hash == hash_secret(browser.cookies.get(SESSION_COOKIE_NAME)),
        ))
        assert current_token is not None
        current_account_id = current_token.account_id
        invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_secret(target_invite)))
        assert invitation is not None
        assert invitation.used_at is None
        assert db.scalar(select(LedgerMember).where(
            LedgerMember.ledger_id == target_ledger,
            LedgerMember.account_id == current_account_id,
        )) is None

    # The error page presents the new identity for a fresh explicit confirmation.
    accepted = browser.post(
        "/web/auth/join/accept", data=_hidden_fields(refused.text), headers=origin, follow_redirects=False,
    )
    assert accepted.status_code == 303, accepted.text
    with SessionLocal() as db:
        invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_secret(target_invite)))
        assert invitation is not None
        assert invitation.used_by_account_id == current_account_id
