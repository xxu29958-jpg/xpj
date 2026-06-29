"""ADR-0051 current-ledger recycle-bin API + /web coverage."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import MonthlyIncomePlan
from app.services.classify_service import create_rule, delete_rule
from app.services.income_plan_service import archive_income_plan, create_income_plan


def _seed_archived_income(
    *,
    tenant_id: str = "owner",
    label: str = "回收站收入",
) -> tuple[str, int]:
    with SessionLocal() as db:
        plan = create_income_plan(
            db,
            tenant_id=tenant_id,
            label=label,
            source_type="salary",
            amount_cents=123400,
            pay_day=28,
            frequency="one_time",
            income_month="2026-06",
        )
        archived = archive_income_plan(
            db,
            tenant_id=tenant_id,
            public_id=plan.public_id,
            expected_row_version=plan.row_version,
        )
        return archived.public_id, archived.row_version


def _seed_deleted_rule() -> int:
    with SessionLocal() as db:
        rule = create_rule(
            db,
            tenant_id="owner",
            keyword="回收站规则",
            category="餐饮",
            enabled=True,
            priority=10,
        )
        rule_id = rule.id
        delete_rule(db, rule, expected_row_version=rule.row_version)
        return rule_id


def test_recycle_bin_api_lists_current_ledger_only(
    client: TestClient, *, identity
) -> None:
    _seed_archived_income(label="本账本收入")
    _seed_archived_income(tenant_id="tester_1", label="其它账本收入")
    _seed_deleted_rule()

    response = client.get("/api/recycle-bin", headers=identity.app_headers)

    assert response.status_code == 200
    body = response.json()
    titles = [item["title"] for item in body["items"]]
    assert "本账本收入" in titles
    assert "回收站规则" in titles
    assert "其它账本收入" not in titles
    assert body["short_window_count"] == 1


def test_recycle_bin_api_restores_archived_income(
    client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_archived_income()

    response = client.post(
        "/api/recycle-bin/restore",
        headers=identity.app_headers,
        json={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": row_version,
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "收入记录已恢复。"
    with SessionLocal() as db:
        status = db.scalar(
            select(MonthlyIncomePlan.status).where(
                MonthlyIncomePlan.public_id == public_id
            )
        )
    assert status == "active"


def test_web_recycle_bin_lists_and_restores_income(
    web_client: TestClient, *, identity
) -> None:
    public_id, row_version = _seed_archived_income(label="网页回收收入")

    list_response = web_client.get("/web/recycle-bin")

    assert list_response.status_code == 200
    body = list_response.text
    assert "回收站" in body
    assert "网页回收收入" in body
    assert f'value="{row_version}"' in body

    restore_response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with SessionLocal() as db:
        status = db.scalar(
            select(MonthlyIncomePlan.status).where(
                MonthlyIncomePlan.public_id == public_id
            )
        )
    assert status == "active"
