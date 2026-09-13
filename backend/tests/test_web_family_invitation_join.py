"""Public Web handoff for one family-ledger invitation."""

from __future__ import annotations

import re

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Invitation, LedgerMember
from app.routes.web_auth import (
    PAIRING_ATTEMPT_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from app.services.identity_service import hash_secret
from tests._web_public_session_support import (
    PUBLIC_HOST,
    mint_session,
    public_client,
)
from tests.test_family_ledger_permissions import _mint_foreign_ledger_invitation


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def _hidden_fields(html: str) -> dict[str, str]:
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html))


def test_public_native_form_previews_invitation_without_consuming_it() -> None:
    _, invite_token = _mint_foreign_ledger_invitation(role="viewer")
    browser = public_client()

    entry = browser.get("/web/auth/join")

    assert entry.status_code == 200, entry.text
    assert invite_token not in entry.text
    assert 'action="/web/auth/join/preview"' in entry.text
    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert preview.status_code == 200, preview.text
    assert "另一家庭账本" in preview.text
    assert "只读" in preview.text
    assert 'action="/web/auth/join/accept"' in preview.text
    assert f'name="invite_token" value="{invite_token}"' in preview.text
    assert invite_token not in str(preview.request.url)
    assert preview.headers["cache-control"] == "no-store"
    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation).where(
                Invitation.token_hash == hash_secret(invite_token)
            )
        )
        assert invitation is not None
        assert invitation.used_at is None
        assert invitation.used_by_account_id is None


def test_no_js_accepts_configured_invite_link_but_rejects_another_host(
    monkeypatch,
) -> None:
    _, invite_token = _mint_foreign_ledger_invitation()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://family.example.com")
    get_settings.cache_clear()
    try:
        browser = public_client()
        entry = browser.get("/web/auth/join")
        invite_url = (
            "https://family.example.com/web/auth/join#invite=" + invite_token
        )

        preview = browser.post(
            "/web/auth/join/preview",
            data={"csrf_token": _csrf(entry.text), "invite_token": invite_url},
            headers={"Origin": f"https://{PUBLIC_HOST}"},
        )

        assert preview.status_code == 200, preview.text
        assert f'name="invite_token" value="{invite_token}"' in preview.text

        hostile = browser.post(
            "/web/auth/join/preview",
            data={
                "csrf_token": _csrf(preview.text),
                "invite_token": (
                    "https://attacker.example/web/auth/join#invite=" + invite_token
                ),
            },
            headers={"Origin": f"https://{PUBLIC_HOST}"},
        )
        assert hostile.status_code == 422
        assert "只能使用家人发来的小票夹邀请链接" in hostile.text
    finally:
        get_settings.cache_clear()


def test_new_browser_identity_accepts_then_reviews_the_joined_family() -> None:
    ledger_id, invite_token = _mint_foreign_ledger_invitation(role="member")
    browser = public_client()
    entry = browser.get("/web/auth/join")
    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert preview.status_code == 200, preview.text
    assert browser.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    accepted = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(preview.text),
            "csrf_token": _csrf(preview.text),
            "invite_token": invite_token,
            "account_name": "阿青",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )

    assert accepted.status_code == 303, accepted.text
    assert accepted.headers["location"] == f"/web/pending?ledger_id={ledger_id}"
    session_token = browser.cookies.get(SESSION_COOKIE_NAME)
    assert session_token
    assert browser.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME) is None
    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation).where(
                Invitation.token_hash == hash_secret(invite_token)
            )
        )
        assert invitation is not None
        assert invitation.used_at is not None
        account = db.scalar(select(Account).where(Account.display_name == "阿青"))
        assert account is not None
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == account.id)
        )
        assert membership is not None
        assert membership.role == "member"
        token = db.scalar(
            select(AuthToken).where(
                AuthToken.token_hash == hash_secret(session_token)
            )
        )
        assert token is not None
        assert token.ledger_id == ledger_id
        device = db.get(Device, token.device_id)
        assert device is not None
        assert device.platform == "web"
        assert device.device_name == "浏览器"
    landing = browser.get(accepted.headers["location"])
    assert landing.status_code == 200, landing.text
    assert "另一家庭账本" in landing.text


def test_existing_browser_identity_joins_after_old_membership_is_disabled(
    client,
    identity,
) -> None:
    session_token = mint_session(client, identity=identity)
    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(
                AuthToken.token_hash == hash_secret(session_token)
            )
        )
        assert token is not None
        old_membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == token.ledger_id)
            .where(LedgerMember.account_id == token.account_id)
        )
        assert old_membership is not None
        old_membership.disabled_at = token.created_at
        account_id = token.account_id
        account = db.get(Account, account_id)
        assert account is not None
        account_name = account.display_name
        db.commit()
    ledger_id, invite_token = _mint_foreign_ledger_invitation(role="viewer")
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, session_token)
    entry = browser.get("/web/auth/join")

    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert preview.status_code == 200, preview.text
    assert account_name in preview.text
    assert 'name="account_name"' not in preview.text
    assert browser.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME) is None
    accepted = browser.post(
        "/web/auth/join/accept",
        data=_hidden_fields(preview.text),
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )

    assert accepted.status_code == 303, accepted.text
    assert accepted.headers["location"] == (
        f"/web/confirmed?ledger_id={ledger_id}"
    )
    assert browser.cookies.get(SESSION_COOKIE_NAME) == session_token
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == account_id)
        )
        assert membership is not None
        assert membership.role == "viewer"
        assert membership.disabled_at is None
    landing = browser.get(accepted.headers["location"])
    assert landing.status_code == 200, landing.text
    assert "另一家庭账本" in landing.text


def test_blank_new_identity_name_keeps_the_invitation_form_recoverable() -> None:
    _, invite_token = _mint_foreign_ledger_invitation()
    browser = public_client()
    entry = browser.get("/web/auth/join")
    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    rejected = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(preview.text),
            "csrf_token": _csrf(preview.text),
            "invite_token": invite_token,
            "account_name": "   ",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert rejected.status_code == 422, rejected.text
    assert "请填写你的称呼" in rejected.text
    assert f'name="invite_token" value="{invite_token}"' in rejected.text
    assert browser.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation).where(
                Invitation.token_hash == hash_secret(invite_token)
            )
        )
        assert invitation is not None
        assert invitation.used_at is None

    corrected = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(rejected.text),
            "csrf_token": _csrf(rejected.text),
            "invite_token": invite_token,
            "account_name": "阿青",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert corrected.status_code == 303, corrected.text


def test_invalid_browser_cookie_cannot_silently_create_a_new_identity() -> None:
    _, invite_token = _mint_foreign_ledger_invitation()
    browser = public_client()
    entry = browser.get("/web/auth/join")
    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )
    browser.cookies.set(
        SESSION_COOKIE_NAME,
        "tbx_invalid_web_session",
        domain=PUBLIC_HOST,
        path="/",
    )

    rejected = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(preview.text),
            "csrf_token": _csrf(preview.text),
            "invite_token": invite_token,
            "account_name": "不应创建的身份",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert rejected.status_code == 401, rejected.text
    assert "登录状态已失效" in rejected.text
    assert 'value="不应创建的身份"' in rejected.text
    assert browser.cookies.get(SESSION_COOKIE_NAME) is None
    assert browser.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    with SessionLocal() as db:
        assert db.scalar(
            select(Account).where(Account.display_name == "不应创建的身份")
        ) is None
        invitation = db.scalar(
            select(Invitation).where(
                Invitation.token_hash == hash_secret(invite_token)
            )
        )
        assert invitation is not None
        assert invitation.used_at is None


def test_two_preview_tabs_keep_their_own_invitation_target() -> None:
    first_ledger_id, first_token = _mint_foreign_ledger_invitation(role="member")
    second_ledger_id, second_token = _mint_foreign_ledger_invitation(role="viewer")
    browser = public_client()
    entry = browser.get("/web/auth/join")
    first_preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": first_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )
    second_entry = browser.get("/web/auth/join")
    second_preview = browser.post(
        "/web/auth/join/preview",
        data={
            "csrf_token": _csrf(second_entry.text),
            "invite_token": second_token,
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert f'name="invite_token" value="{first_token}"' in first_preview.text
    assert second_token not in first_preview.text
    assert f'name="invite_token" value="{second_token}"' in second_preview.text
    assert first_token not in second_preview.text
    first_accept = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(first_preview.text),
            "csrf_token": _csrf(first_preview.text),
            "invite_token": first_token,
            "account_name": "双标签成员",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert first_accept.status_code == 303, first_accept.text
    session_token = browser.cookies.get(SESSION_COOKIE_NAME)

    second_accept = browser.post(
        "/web/auth/join/accept",
        data={
            **_hidden_fields(second_preview.text),
            "csrf_token": _csrf(second_preview.text),
            "invite_token": second_token,
            "account_name": "不应成为第二身份",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )

    assert second_accept.status_code == 303, second_accept.text
    assert browser.cookies.get(SESSION_COOKIE_NAME) == session_token
    with SessionLocal() as db:
        account = db.scalar(
            select(Account).where(Account.display_name == "双标签成员")
        )
        assert account is not None
        assert db.scalar(
            select(Account).where(Account.display_name == "不应成为第二身份")
        ) is None
        memberships = db.scalars(
            select(LedgerMember).where(
                LedgerMember.account_id == account.id,
                LedgerMember.ledger_id.in_([first_ledger_id, second_ledger_id]),
            )
        ).all()
        assert {(item.ledger_id, item.role) for item in memberships} == {
            (first_ledger_id, "member"),
            (second_ledger_id, "viewer"),
        }


def test_lost_first_accept_response_recovers_with_the_same_enrollment_proof() -> None:
    _, invite_token = _mint_foreign_ledger_invitation()
    browser = public_client()
    entry = browser.get("/web/auth/join")
    preview = browser.post(
        "/web/auth/join/preview",
        data={"csrf_token": _csrf(entry.text), "invite_token": invite_token},
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )
    lost_response_client = public_client()
    for cookie in browser.cookies.jar:
        lost_response_client.cookies.set(
            cookie.name,
            cookie.value,
            domain=PUBLIC_HOST,
            path=cookie.path,
        )
    form = {
        **_hidden_fields(preview.text),
        "csrf_token": _csrf(preview.text),
        "invite_token": invite_token,
        "account_name": "断线后恢复",
    }

    first = lost_response_client.post(
        "/web/auth/join/accept",
        data=form,
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )

    assert first.status_code == 303, first.text
    first_session = lost_response_client.cookies.get(SESSION_COOKIE_NAME)
    assert first_session
    assert browser.cookies.get(SESSION_COOKIE_NAME) is None
    retried = browser.post(
        "/web/auth/join/accept",
        data=form,
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert retried.status_code == 303, retried.text
    assert browser.cookies.get(SESSION_COOKIE_NAME) == first_session
