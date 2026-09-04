"""Product Web consumer for household members and invitations."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Invitation, Ledger, LedgerMember
from app.routes import owner_ledgers
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.pairing_test_support import invitation_accept_payload


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def _create_invitation(
    web_client: TestClient,
    *,
    role: str = "member",
    note: str = "妈妈",
) -> tuple[str, str]:
    page = web_client.get("/web/family?ledger_id=owner")
    assert page.status_code == 200, page.text
    response = web_client.post(
        "/web/family/invitations?ledger_id=owner",
        data={
            "csrf_token": _csrf(page.text),
            "role": role,
            "note": note,
            "ttl_days": "7",
        },
    )
    assert response.status_code == 200, response.text
    tokens = re.findall(r"inv_[A-Za-z0-9_-]{20,}", response.text)
    assert len(tokens) == 1, tokens
    return tokens[0], response.text


def _accept_member(
    client: TestClient,
    invite_token: str,
    *,
    account_name: str,
) -> tuple[int, str]:
    accepted = client.post(
        "/api/invitations/accept",
        json=invitation_accept_payload(
            invite_token,
            account_name=account_name,
            device_name=f"{account_name}-phone",
        ),
    )
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id != 1)
            .where(LedgerMember.disabled_at.is_(None))
            .order_by(LedgerMember.id.desc())
            .limit(1)
        )
        assert member is not None
        return int(member.id), accepted.json()["session_token"]


def _open_member_web_session(
    client: TestClient,
    *,
    session_token: str,
) -> TestClient:
    pairing = client.post(
        "/api/ledgers/owner/devices/pairing-codes",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"ttl_minutes": 15},
    )
    assert pairing.status_code == 201, pairing.text
    viewer = public_client()
    login_form = viewer.get("/web/auth/login")
    assert login_form.status_code == 200, login_form.text
    login = viewer.post(
        "/web/auth/login",
        data={
            "pairing_code": pairing.json()["pairing_code"],
            "device_name": "pytest family browser",
            "csrf_token": _csrf(login_form.text),
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
        follow_redirects=False,
    )
    assert login.status_code == 303, login.text
    assert viewer.cookies.get(SESSION_COOKIE_NAME)
    return viewer


def test_family_is_a_real_responsive_product_destination(web_client: TestClient) -> None:
    response = web_client.get("/web/family?ledger_id=owner")

    assert response.status_code == 200
    assert 'data-domain="obligations"' in response.text
    assert 'aria-current="page">家庭' in response.text
    assert "家庭成员" in response.text
    assert 'name="csrf_token"' in response.text
    assert 'href="/web/family?ledger_id=owner"' in response.text


def test_owner_creates_one_time_invitation_and_can_revoke_it(
    web_client: TestClient,
) -> None:
    invite_token, created_html = _create_invitation(web_client)

    assert "仅显示一次" in created_html
    assert "妈妈" in created_html
    assert created_html.count(invite_token) == 1
    assert 'data-family-copy-button' in created_html
    assert 'src="/static/web/family.js' in created_html
    assert "我有家庭邀请" in created_html
    assert "设置 → 加入家庭账本" in created_html
    listed = web_client.get("/web/family?ledger_id=owner")
    assert listed.status_code == 200
    assert invite_token not in listed.text
    assert "妈妈" in listed.text
    assert "待接受" in listed.text
    public_id = re.search(r"/web/family/invitations/([^/\"?]+)/revoke", listed.text)
    assert public_id is not None, listed.text

    revoked = web_client.post(
        f"/web/family/invitations/{public_id.group(1)}/revoke?ledger_id=owner",
        data={"csrf_token": _csrf(listed.text)},
        follow_redirects=False,
    )

    assert revoked.status_code == 303
    after = web_client.get(revoked.headers["location"])
    assert "已撤销" in after.text
    assert "撤销邀请" in after.text


def test_public_owner_session_creates_an_invitation(
    client: TestClient,
    identity,
) -> None:
    owner = public_client()
    owner.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity))
    page = owner.get("/web/family?ledger_id=owner")

    response = owner.post(
        "/web/family/invitations?ledger_id=owner",
        data={
            "csrf_token": _csrf(page.text),
            "role": "member",
            "note": "外婆",
            "ttl_days": "7",
        },
        headers={"Origin": f"https://{PUBLIC_HOST}"},
    )

    assert response.status_code == 200, response.text
    assert "邀请已生成" in response.text
    assert "外婆" in response.text


def test_owner_changes_role_and_disables_member(
    client: TestClient,
    web_client: TestClient,
) -> None:
    invite_token, _ = _create_invitation(web_client, note="爸爸")
    member_id, _ = _accept_member(client, invite_token, account_name="爸爸")
    page = web_client.get("/web/family?ledger_id=owner")

    role = web_client.post(
        f"/web/family/members/{member_id}/role?ledger_id=owner",
        data={"csrf_token": _csrf(page.text), "role": "viewer"},
        follow_redirects=False,
    )
    assert role.status_code == 303
    changed = web_client.get(role.headers["location"])
    assert "爸爸" in changed.text
    assert "只读" in changed.text
    assert "成员 → 只读" in changed.text

    disabled = web_client.post(
        f"/web/family/members/{member_id}/disable?ledger_id=owner",
        data={"csrf_token": _csrf(changed.text)},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    after = web_client.get(disabled.headers["location"])
    assert "已停用" in after.text
    assert "停用于" in after.text
    assert "停用成员" in after.text


def test_viewer_sees_roster_without_owner_commands(
    client: TestClient,
    web_client: TestClient,
) -> None:
    invite_token, _ = _create_invitation(web_client, role="viewer", note="妹妹")
    _, session_token = _accept_member(client, invite_token, account_name="妹妹")
    viewer = _open_member_web_session(client, session_token=session_token)

    response = viewer.get("/web/family?ledger_id=owner")

    assert response.status_code == 200
    assert "妹妹" in response.text
    assert "当前角色可以查看家庭成员" in response.text
    assert "/web/family/invitations?" not in response.text
    assert "/role?" not in response.text
    assert "/disable?" not in response.text
    assert "/transfer-owner?" not in response.text


def test_invalid_member_change_keeps_the_roster_and_error_on_the_same_page(
    client: TestClient,
    web_client: TestClient,
) -> None:
    invite_token, _ = _create_invitation(web_client, note="爸爸")
    member_id, _ = _accept_member(client, invite_token, account_name="爸爸")
    page = web_client.get("/web/family?ledger_id=owner")

    response = web_client.post(
        f"/web/family/members/{member_id}/role?ledger_id=owner",
        data={"csrf_token": _csrf(page.text), "role": "owner"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "成员角色只能是成员或只读" in response.text
    assert "爸爸" in response.text


def test_expired_invitation_is_localized_and_not_presented_as_usable(
    web_client: TestClient,
) -> None:
    _create_invitation(web_client, note="旧邀请")
    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation)
            .where(Invitation.ledger_id == "owner")
            .order_by(Invitation.id.desc())
            .limit(1)
        )
        assert invitation is not None
        invitation.created_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        invitation.expires_at = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
        public_id = invitation.public_id
        db.commit()

    response = web_client.get("/web/family?ledger_id=owner")

    assert response.status_code == 200
    assert "2026-01-01 18:00" in response.text
    assert "2026-01-01 19:00" in response.text
    assert "已过期" in response.text
    assert "旧邀请" in response.text
    assert f"/web/family/invitations/{public_id}/revoke" not in response.text


def test_owner_transfers_the_single_owner_role(
    client: TestClient,
    web_client: TestClient,
) -> None:
    invite_token, _ = _create_invitation(web_client, note="姐姐")
    member_id, _ = _accept_member(client, invite_token, account_name="姐姐")
    page = web_client.get("/web/family?ledger_id=owner")

    transferred = web_client.post(
        f"/web/family/members/{member_id}/transfer-owner?ledger_id=owner",
        data={"csrf_token": _csrf(page.text), "confirmed": "yes"},
        follow_redirects=False,
    )

    assert transferred.status_code == 303
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        owners = list(
            db.scalars(
                select(LedgerMember)
                .where(LedgerMember.ledger_id == "owner")
                .where(LedgerMember.role == "owner")
                .where(LedgerMember.disabled_at.is_(None))
            )
        )
        target = db.get(LedgerMember, member_id)
        assert ledger is not None and target is not None
        assert ledger.owner_account_id == target.account_id
        assert [row.id for row in owners] == [member_id]


def test_owner_console_members_surface_is_retired_to_the_product(
    web_client: TestClient,
) -> None:
    app.dependency_overrides[owner_ledgers._require_local] = lambda: None
    try:
        ledgers = web_client.get("/owner/ledgers")
        retired = web_client.get("/owner/ledgers/owner/members")
    finally:
        app.dependency_overrides.pop(owner_ledgers._require_local, None)

    assert ledgers.status_code == 200
    assert "/owner/ledgers/owner/members" not in ledgers.text
    assert "/web/family?ledger_id=owner" in ledgers.text
    assert retired.status_code == 404
