"""v0.4-beta1: verify /web shows role chip + hides write affordances for viewer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from app.routes.web_app import _require_local as _web_require_local

@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _make_ledger_with_role(client: TestClient, role: str, *, identity) -> str:
    resp = client.post(
        "/api/ledgers", headers=identity.admin_headers, json={"name": f"{role}_ledger"}
    )
    assert resp.status_code == 201, resp.json()
    lid = resp.json()["ledger_id"]
    with SessionLocal() as db:
        # The owner-account's row for this new ledger is the only member.
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == lid).limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()
    return lid


def _seed_pending(ledger_id: str) -> int:
    from app.models import Expense
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        now = now_utc()
        exp = Expense(
            tenant_id=ledger_id,
            amount_cents=1234,
            merchant="test",
            category="其他",
            note="",
            source="manual",
            image_path=None,
            thumbnail_path=None,
            image_hash=None,
            raw_text="",
            confidence=None,
            status="pending",
            expense_time=now,
            created_at=now,
            updated_at=now,
        )
        db.add(exp)
        db.commit()
        return exp.id


def test_web_pending_shows_owner_role_chip_by_default(web_client: TestClient) -> None:
    _seed_pending("owner")
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    assert "ledger-role-chip" in resp.text
    assert "拥有者" in resp.text
    assert "个人账本" in resp.text
    # owner can write → bulk-actions visible.
    assert "批量确认" in resp.text


def test_web_pending_viewer_hides_bulk_actions(web_client: TestClient, *, identity) -> None:
    lid = _make_ledger_with_role(web_client, "viewer", identity=identity)
    _seed_pending(lid)
    resp = web_client.get(f"/web/pending?ledger_id={lid}")
    assert resp.status_code == 200
    assert "ledger-role-viewer" in resp.text
    assert "只读" in resp.text
    # viewer banner present.
    assert "只读角色" in resp.text
    # Bulk confirm/reject/keep buttons must be gone.
    assert "批量确认" not in resp.text
    assert "批量忽略" not in resp.text


def test_web_member_role_keeps_write_buttons(web_client: TestClient, *, identity) -> None:
    lid = _make_ledger_with_role(web_client, "member", identity=identity)
    _seed_pending(lid)
    resp = web_client.get(f"/web/pending?ledger_id={lid}")
    assert resp.status_code == 200
    assert "ledger-role-member" in resp.text
    assert "成员" in resp.text
    assert "共享账本" in resp.text
    assert "批量确认" in resp.text


def test_web_edit_viewer_disables_inputs(web_client: TestClient, *, identity) -> None:
    """Viewer can open edit page but inputs are disabled and Save is gone."""
    lid = _make_ledger_with_role(web_client, "viewer", identity=identity)
    eid = _seed_pending(lid)

    resp = web_client.get(f"/web/expenses/{eid}/edit?ledger_id={lid}")
    assert resp.status_code == 200
    assert 'disabled' in resp.text
    # Save / 入账 / 忽略 buttons must be hidden.
    assert "保存</button>" not in resp.text
    assert "入账</button>" not in resp.text
