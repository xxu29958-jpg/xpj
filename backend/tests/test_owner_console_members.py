"""Owner Console smoke tests for /owner/ledgers/{lid}/members."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import conftest as cf  # noqa: F401  — ensures module-level seeds run
from app.main import app
from app.routes.owner_console import _require_local as _require_local_console
from app.routes.owner_ledgers import _require_local as _require_local_ledgers
from conftest import admin_headers


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local_console] = lambda: None
    app.dependency_overrides[_require_local_ledgers] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local_console, None)
    app.dependency_overrides.pop(_require_local_ledgers, None)


def _create_ledger(client: TestClient, name: str = "家庭账本") -> str:
    resp = client.post("/api/ledgers", headers=admin_headers(), json={"name": name})
    assert resp.status_code == 201, resp.json()
    return str(resp.json()["ledger_id"])


def _mint_and_accept_member(local_client: TestClient, ledger_id: str, account_name: str) -> int:
    invite_resp = local_client.post(
        f"/owner/ledgers/{ledger_id}/invitations",
        data={"role": "member", "note": account_name, "ttl_days": "7"},
    )
    assert invite_resp.status_code == 200
    invite = re.findall(r"inv_[A-Za-z0-9_\-]{20,}", invite_resp.text)[0]

    accept = local_client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite,
            "account_name": account_name,
            "device_name": f"{account_name}-Phone",
            "platform": "android",
        },
    )
    assert accept.status_code == 200

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import LedgerMember

    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.role == "member")
            .limit(1)
        )
        assert member is not None
        return int(member.id)


def test_members_page_local_200(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    resp = local_client.get(f"/owner/ledgers/{lid}/members")
    assert resp.status_code == 200
    assert "成员管理" in resp.text
    assert "家庭账本" in resp.text


def test_members_page_uses_consistent_chips_and_breakable_text(local_client: TestClient) -> None:
    long_name = "家庭共享账本" + ("很长" * 12)
    long_note = "备注" + ("很长" * 20)
    lid = _create_ledger(local_client, name=long_name)

    resp = local_client.post(
        f"/owner/ledgers/{lid}/invitations",
        data={"role": "viewer", "note": long_note, "ttl_days": "7"},
    )

    assert resp.status_code == 200
    assert long_name in resp.text
    assert long_note in resp.text
    assert 'class="ledger-title text-break"' in resp.text
    assert 'class="one-time-secret"' in resp.text
    assert 'class="table-scroll"' in resp.text
    assert 'class="text-break"' in resp.text
    assert 'class="role-chip role-owner"' in resp.text
    assert 'class="role-chip role-viewer"' in resp.text
    assert 'class="status-chip status-active"' in resp.text
    assert 'class="status-chip status-pending"' in resp.text


def test_members_page_remote_403(client: TestClient) -> None:
    lid = _create_ledger(client)
    resp = client.get(f"/owner/ledgers/{lid}/members")
    assert resp.status_code == 403


def test_members_page_unknown_ledger_shows_error(local_client: TestClient) -> None:
    resp = local_client.get("/owner/ledgers/lg_nope/members")
    assert resp.status_code == 200
    assert "账本不存在" in resp.text


def test_invitation_create_revokes_and_lists(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    resp = local_client.post(
        f"/owner/ledgers/{lid}/invitations",
        data={"role": "member", "note": "妈妈", "ttl_days": "7"},
    )
    assert resp.status_code == 200
    tokens = re.findall(r"inv_[A-Za-z0-9_\-]{20,}", resp.text)
    assert len(tokens) == 1, tokens
    invite_token = tokens[0]

    list_resp = local_client.get(f"/owner/ledgers/{lid}/members")
    assert list_resp.status_code == 200
    assert invite_token not in list_resp.text
    assert "妈妈" in list_resp.text
    assert "待接受" in list_resp.text
    assert "成员审计" in list_resp.text
    assert "创建邀请" in list_resp.text

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Invitation

    with SessionLocal() as db:
        inv = db.scalar(select(Invitation).where(Invitation.ledger_id == lid).limit(1))
        assert inv is not None
        public_id = inv.public_id

    revoke = local_client.post(
        f"/owner/ledgers/{lid}/invitations/{public_id}/revoke",
        follow_redirects=False,
    )
    assert revoke.status_code == 303

    after = local_client.get(f"/owner/ledgers/{lid}/members")
    assert "已撤销" in after.text
    assert "撤销邀请" in after.text
    assert public_id not in after.text


def test_disable_member_endpoint(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import LedgerMember

    with SessionLocal() as db:
        owner_member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == lid).limit(1)
        )
        assert owner_member is not None
        owner_mid = owner_member.id

    resp = local_client.post(
        f"/owner/ledgers/{lid}/members/{owner_mid}/disable",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "成员管理" in resp.text


def test_role_update_form_changes_member_role(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    member_id = _mint_and_accept_member(local_client, lid, "爸爸")

    role_change = local_client.post(
        f"/owner/ledgers/{lid}/members/{member_id}/role",
        data={"role": "viewer"},
        follow_redirects=False,
    )
    assert role_change.status_code == 303

    page = local_client.get(f"/owner/ledgers/{lid}/members")
    assert page.status_code == 200
    assert "爸爸" in page.text
    assert "只读" in page.text
    assert 'class="role-chip role-viewer"' in page.text
    assert "调整角色" in page.text


def test_owner_console_transfer_owner_form_demotes_local_owner(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    member_id = _mint_and_accept_member(local_client, lid, "姐姐")

    transfer = local_client.post(
        f"/owner/ledgers/{lid}/members/{member_id}/transfer-owner",
        follow_redirects=False,
    )
    assert transfer.status_code == 303

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Ledger, LedgerMember

    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == lid))
        owner_rows = list(
            db.scalars(
                select(LedgerMember)
                .where(LedgerMember.ledger_id == lid)
                .where(LedgerMember.role == "owner")
                .where(LedgerMember.disabled_at.is_(None))
            )
        )
        target = db.get(LedgerMember, member_id)
        assert ledger is not None and target is not None
        assert len(owner_rows) == 1
        assert ledger.owner_account_id == target.account_id

    page = local_client.get(f"/owner/ledgers/{lid}/members")
    assert page.status_code == 200
    assert "当前本机账号不是这个账本的拥有者" in page.text
    assert f"/owner/ledgers/{lid}/members/{member_id}/transfer-owner" not in page.text


def test_ledgers_page_links_to_members(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    resp = local_client.get("/owner/ledgers")
    assert resp.status_code == 200
    assert f"/owner/ledgers/{lid}/members" in resp.text
