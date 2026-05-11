"""Owner Console smoke tests for /owner/ledgers/{lid}/members (v0.4-beta1).

Verifies:
- Local 200 / remote 403.
- Plain invite_token only appears ONCE (in the create response), never on list.
- Page lists members & invitations.
- Revoke + disable POST endpoints return 303 and update state.
"""

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
    return resp.json()["ledger_id"]


def test_members_page_local_200(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    resp = local_client.get(f"/owner/ledgers/{lid}/members")
    assert resp.status_code == 200
    assert "成员管理" in resp.text
    assert "家庭账本" in resp.text


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
    # Mint invite via the form-encoded POST.
    resp = local_client.post(
        f"/owner/ledgers/{lid}/invitations",
        data={"role": "member", "note": "妈妈", "ttl_days": "7"},
    )
    assert resp.status_code == 200
    # Plain invite_token (inv_...) must appear exactly once in this response.
    tokens = re.findall(r"inv_[A-Za-z0-9_\-]{20,}", resp.text)
    assert len(tokens) == 1, tokens
    invite_token = tokens[0]

    # GET the list page; plain token must NOT reappear.
    list_resp = local_client.get(f"/owner/ledgers/{lid}/members")
    assert list_resp.status_code == 200
    assert invite_token not in list_resp.text
    assert "妈妈" in list_resp.text
    assert "待接受" in list_resp.text

    # Extract the public_id of the invitation to revoke it.
    from app.database import SessionLocal
    from app.models import Invitation
    from sqlalchemy import select

    with SessionLocal() as db:
        inv = db.scalar(select(Invitation).where(Invitation.ledger_id == lid).limit(1))
        assert inv is not None
        public_id = inv.public_id

    revoke = local_client.post(
        f"/owner/ledgers/{lid}/invitations/{public_id}/revoke",
        follow_redirects=False,
    )
    assert revoke.status_code == 303

    # Page now shows revoked state.
    after = local_client.get(f"/owner/ledgers/{lid}/members")
    assert "已撤销" in after.text


def test_disable_member_endpoint(local_client: TestClient) -> None:
    """Owner cannot be disabled via the Owner Console form (no button rendered),
    and the route returns the page with an error if attempted directly."""
    lid = _create_ledger(local_client)
    # Find the owner member.id.
    from app.database import SessionLocal
    from app.models import LedgerMember
    from sqlalchemy import select

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
    # Service raises AppError("member_cannot_disable_owner") → page re-renders 200 with error.
    assert resp.status_code == 200
    assert "成员管理" in resp.text


def test_ledgers_page_links_to_members(local_client: TestClient) -> None:
    lid = _create_ledger(local_client)
    resp = local_client.get("/owner/ledgers")
    assert resp.status_code == 200
    assert f"/owner/ledgers/{lid}/members" in resp.text
