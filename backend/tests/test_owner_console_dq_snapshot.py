"""Tests for the PR19 Owner Console data-quality snapshot card."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload(client: TestClient, *, identity) -> int:
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=PNG,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_owner_index_renders_dq_snapshot(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert "运营快照" in body
    assert "可一键入账" in body
    assert "疑似重复" in body


def test_owner_index_dq_counts_update_after_upload(local_client: TestClient, *, identity) -> None:
    # Two uploads with the same image hash → second is flagged suspected.
    _upload(local_client, identity=identity)
    _upload(local_client, identity=identity)
    body = local_client.get("/owner").text
    assert "运营快照" in body
    # Quick link to the new /web pages is rendered.
    assert "/web/duplicates" in body
    assert "/web/data-quality" in body
    assert "/web/categories/uncategorized" in body
    assert "/web/import" in body
    assert "/web/export.csv" in body


def test_owner_index_dq_no_secret_leak(local_client: TestClient, *, identity) -> None:
    _upload(local_client, identity=identity)
    body = local_client.get("/owner").text
    assert identity.app_token not in body
    assert identity.admin_token not in body
    assert identity.upload_key not in body


def test_owner_index_ready_stat_uses_categorized_caliber(local_client: TestClient, *, identity) -> None:
    """PR #230 round 9: the 可一键入账 stat must match the /web/data-quality
    ready action count (categorized) — the 未分类 row must not inflate it."""
    from app.database import SessionLocal
    from app.models import Expense

    with SessionLocal() as db:
        db.add_all(
            [
                Expense(
                    tenant_id="owner", amount_cents=100, merchant="星巴克", category="餐饮",
                    source="pytest", status="pending", duplicate_status="none",
                ),
                Expense(
                    tenant_id="owner", amount_cents=200, merchant="麦当劳", category="未分类",
                    source="pytest", status="pending", duplicate_status="none",
                ),
            ]
        )
        db.commit()

    body = local_client.get("/owner").text
    assert '<div class="num">1</div>\n      <div class="label">可一键入账</div>' in body


def test_owner_home_keeps_managed_and_primary_ledger_scopes_distinct(local_client: TestClient) -> None:
    """Moving home sections must not relabel a primary-ledger count as the total."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Expense, LedgerMember
    from app.services import owner_console_service as svc
    from app.services.ledger_service import create_ledger

    with SessionLocal() as db:
        before = svc.get_index_vm(db)
        owner_id = db.scalar(select(LedgerMember.account_id).where(
            LedgerMember.ledger_id == before.primary_tenant_id,
            LedgerMember.role == "owner",
        ))
        other = create_ledger(db, account_id=owner_id, name="旅行账本", auth=None)
        for ledger_id, count in [(before.primary_tenant_id, 2), (other.ledger_id, 5)]:
            db.add_all([
                Expense(tenant_id=ledger_id, amount_cents=1850, merchant="早餐",
                        category="餐饮", status="pending", source="manual", duplicate_status="none")
                for _ in range(count)
            ])
        db.commit()
        vm = svc.get_index_vm(db)
        rows = {row.ledger_id: row for row in svc.list_ledger_health(db)}

    assert vm.pending_count == before.pending_count + 7
    assert vm.dq_summary.pending_total == before.dq_summary.pending_total + 2
    assert rows[other.ledger_id].pending == 5
    response = local_client.get("/owner")
    assert response.status_code == 200
    text = " ".join(re.sub(r"<[^>]+>", " ", response.text).split())
    assert "你管理的全部账本" in text
    assert "当前账号" in text
    assert "主账本" in text
    assert vm.ledger_name in text and "旅行账本" in text
    assert re.search(rf"\b{vm.pending_count}\s+待确认", text)
    assert f"/web/data-quality?ledger_id={other.ledger_id}" in response.text
    audit_heading = re.search(r"<h2>规则应用审计(.*?)</h2>", response.text, re.DOTALL)
    assert audit_heading is not None
    assert vm.ledger_name in audit_heading.group(1)
    assert "全部账本" not in audit_heading.group(1)
