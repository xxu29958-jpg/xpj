"""C5b-2 硬门：/web 回收站 restore 失败 → 422 原地重渲染 + 错误锚定到被提交行。

照 #248 (``web_debt_proposal_actions``) 范式钉死：

- OCC 冲突 / 缺 token / 已恢复 / 超窗 / 他账本构造 → 422 原地重渲染，错误按
  ``data-restore-key`` 身份锚 (``kind:resource_id``，不是位置索引) 钉到被提交行；
  行已不在列表时裸块兜底 (``data-restore-orphan``)，文案永不整页消失；
- ``db.rollback()`` 零写入；成功仍 303；viewer 直 POST 仍 403；
- 重试同一提交幂等 (服务层 early-return)，幂等语义不破。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryRule, LedgerMember, MonthlyIncomePlan
from app.services.classify_service import create_rule, delete_rule
from app.services.income_plan_service import archive_income_plan, create_income_plan
from app.services.soft_delete_policy import recycle_bin_retention_days
from app.services.time_service import now_utc

GONE_MESSAGE = "这条项目已不在回收站，可能已恢复或超过保留期，请刷新查看最新状态。"
STALE_MESSAGE = "页面已过期，请刷新后重新操作。"


def _seed_archived_income(
    *,
    tenant_id: str = "owner",
    label: str = "422 回收收入",
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
            keyword="422 回收规则",
            category="餐饮",
            enabled=True,
            priority=10,
        )
        rule_id = rule.id
        delete_rule(db, rule, expected_row_version=rule.row_version)
        return rule_id


def _income_row(public_id: str) -> tuple[str, int]:
    with SessionLocal() as db:
        plan = db.scalar(select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == public_id))
        assert plan is not None
        return plan.status, plan.row_version


def _rule_deleted_at(rule_id: int):
    with SessionLocal() as db:
        return db.scalar(select(CategoryRule.deleted_at).where(CategoryRule.id == rule_id))


def _make_viewer_ledger(client: TestClient, *, identity) -> str:
    response = client.post(
        "/api/ledgers",
        headers=identity.admin_headers,
        json={"name": "recycle-viewer"},
    )
    assert response.status_code == 201, response.json()
    ledger_id = response.json()["ledger_id"]
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == ledger_id).limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()
    return ledger_id


def test_restore_occ_conflict_rerenders_422_anchored_to_row(web_client: TestClient, *, identity) -> None:
    public_id, row_version = _seed_archived_income(label="冲突收入")

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": str(row_version + 1),  # 过期 OCC token
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    html = response.text
    key = f"income_plan:{public_id}"
    # 错误锚定到被提交行：身份锚 + 行上 aria 双锚 + role=alert 错误块各一处。
    assert f'data-restore-key="{key}"' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="recycle-restore-error"' in html
    assert html.count('id="recycle-restore-error"') == 1
    assert html.count('role="alert"') == 1
    assert "data-restore-orphan" not in html
    assert STALE_MESSAGE in html
    # 零写入：状态与 row_version 均未变。
    assert _income_row(public_id) == ("archived", row_version)


def test_restore_missing_token_rerenders_422_anchored_to_row(web_client: TestClient, *, identity) -> None:
    public_id, row_version = _seed_archived_income(label="缺令牌收入")

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={"kind": "income_plan", "resource_id": public_id},
        follow_redirects=False,
    )

    assert response.status_code == 422
    html = response.text
    assert f'data-restore-key="income_plan:{public_id}"' in html
    assert 'aria-invalid="true"' in html
    assert html.count('id="recycle-restore-error"') == 1
    assert "data-restore-orphan" not in html
    assert "页面已过期，请刷新后重试。" in html
    assert _income_row(public_id) == ("archived", row_version)


def test_restore_success_still_303(web_client: TestClient, *, identity) -> None:
    public_id, row_version = _seed_archived_income(label="成功收入")

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/web/recycle-bin")
    status, _ = _income_row(public_id)
    assert status == "active"


def test_restore_retry_same_submission_stays_idempotent_303(web_client: TestClient, *, identity) -> None:
    """幂等语义不破：同一提交重试不旋转、不写两遍 —— 服务层对已成功行 early-return。"""
    public_id, row_version = _seed_archived_income(label="幂等收入")
    payload = {
        "kind": "income_plan",
        "resource_id": public_id,
        "expected_row_version": str(row_version),
    }

    first = web_client.post("/web/recycle-bin/restore", data=payload, follow_redirects=False)
    second = web_client.post("/web/recycle-bin/restore", data=payload, follow_redirects=False)

    assert first.status_code == 303
    assert second.status_code == 303
    status, _ = _income_row(public_id)
    assert status == "active"


def test_restore_viewer_direct_post_still_403(web_client: TestClient, *, identity) -> None:
    ledger_id = _make_viewer_ledger(web_client, identity=identity)

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "ledger_id": ledger_id,
            "kind": "income_plan",
            "resource_id": "whatever",
            "expected_row_version": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"] == "permission_denied"


def test_restore_other_ledger_row_invisible_and_inoperable(web_client: TestClient, *, identity) -> None:
    public_id, row_version = _seed_archived_income(
        tenant_id="tester_1",
        label="他账本回收收入",
    )

    page = web_client.get("/web/recycle-bin")
    assert page.status_code == 200
    assert "他账本回收收入" not in page.text

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={
            "kind": "income_plan",
            "resource_id": public_id,
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    html = response.text
    # 他账本行不在当前账本列表 → 无行可锚 → 裸块兜底，身份锚仍带被提交行。
    assert 'data-restore-orphan="true"' in html
    assert f'data-restore-key="income_plan:{public_id}"' in html
    assert 'role="alert"' in html
    assert GONE_MESSAGE in html
    # 跨账本零写入：他账本行仍是 archived。
    status, _ = _income_row(public_id)
    assert status == "archived"


def test_restore_already_restored_rerenders_422_orphan(web_client: TestClient, *, identity) -> None:
    rule_id = _seed_deleted_rule()
    payload = {"kind": "category_rule", "resource_id": str(rule_id)}

    first = web_client.post("/web/recycle-bin/restore", data=payload, follow_redirects=False)
    assert first.status_code == 303
    assert _rule_deleted_at(rule_id) is None

    second = web_client.post("/web/recycle-bin/restore", data=payload, follow_redirects=False)

    assert second.status_code == 422
    html = second.text
    # 行已恢复 → 不在列表 → 裸块兜底；规则保持已恢复 (零回写)。
    assert 'data-restore-orphan="true"' in html
    assert f'data-restore-key="category_rule:{rule_id}"' in html
    assert GONE_MESSAGE in html
    assert _rule_deleted_at(rule_id) is None


def test_restore_past_recycle_window_rerenders_422_orphan(web_client: TestClient, *, identity) -> None:
    rule_id = _seed_deleted_rule()
    with SessionLocal() as db:
        rule = db.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert rule is not None
        rule.deleted_at = now_utc() - timedelta(days=recycle_bin_retention_days() + 1)
        db.commit()

    response = web_client.post(
        "/web/recycle-bin/restore",
        data={"kind": "category_rule", "resource_id": str(rule_id)},
        follow_redirects=False,
    )

    assert response.status_code == 422
    html = response.text
    assert 'data-restore-orphan="true"' in html
    assert GONE_MESSAGE in html
    # 超窗零写入：deleted_at 保持原样 (仍被软删)。
    assert _rule_deleted_at(rule_id) is not None
