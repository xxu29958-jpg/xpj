"""/web/debt-goals 七个写端点的 POST 闭环测试 (slice C4, 补齐 #218 自身的覆盖缺口).

每个端点都钉三件事：幂等重放返回 canonical 结果且不双写、OCC 过期快照 → 303 带回
「计划已在其它端更新」且不写、校验 422 原地重渲染保留已填值。另钉只读角色 (can_write
false) 无表单且直 POST 被 403。种子经 /api 真路径 (复用 debt_repayment_goal_helpers)，
断言走 /api 读 + ORM 行数，不依赖模板文案。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Goal, LedgerMember
from tests.debt_repayment_goal_helpers import (
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _links_count_for_version,
    _void_debt,
)

_STALE = "计划已在其它端更新，请刷新后重新操作。"


# ── helpers ──────────────────────────────────────────────────────────────────
def _page(web_client: TestClient) -> str:
    resp = web_client.get("/web/debt-goals?ledger_id=owner")
    assert resp.status_code == 200, resp.text
    return resp.text


def _goal_view(web_client: TestClient, headers: dict[str, str], public_id: str) -> dict:
    resp = web_client.get(f"/api/goals/{public_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _goal_row(public_id: str) -> Goal:
    with SessionLocal() as db:
        goal = db.scalar(select(Goal).where(Goal.public_id == public_id))
        assert goal is not None
        db.expunge(goal)
        return goal


def _redirect_error(resp) -> str:
    """The ``error=`` query param of a 303 same-site redirect (decoded)."""
    assert resp.status_code == 303, resp.text
    query = parse_qs(urlparse(resp.headers["location"]).query)
    return (query.get("error") or [""])[0]


def _web_create(web_client: TestClient, *, name: str, debt_ids: list[str], key: str | None = None):
    data: dict[str, object] = {
        "ledger_id": "owner",
        "name": name,
        "idempotency_key": key if key is not None else str(uuid4()),
        "csrf_token": "test-client-bypasses-middleware-check",
        "debt_public_ids": debt_ids,
    }
    return web_client.post("/web/debt-goals/create", data=data, follow_redirects=False)


def _web_goal_post(
    web_client: TestClient,
    public_id: str,
    action: str,
    *,
    row_version: int | str,
    key: str | None = None,
    extra: dict[str, object] | None = None,
):
    data: dict[str, object] = {
        "ledger_id": "owner",
        "expected_row_version": str(row_version),
        "idempotency_key": key if key is not None else str(uuid4()),
        "csrf_token": "test-client-bypasses-middleware-check",
        **(extra or {}),
    }
    return web_client.post(
        f"/web/debt-goals/{public_id}/{action}",
        data=data,
        follow_redirects=False,
    )


def _web_links(
    web_client: TestClient,
    public_id: str,
    *,
    row_version: int | str,
    debt_ids: list[str],
    key: str | None = None,
):
    return _web_goal_post(
        web_client,
        public_id,
        "links",
        row_version=row_version,
        key=key,
        extra={"debt_public_ids": debt_ids},
    )


# ── create ───────────────────────────────────────────────────────────────────
def test_create_happy_path_and_idempotent_replay(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    key = str(uuid4())

    first = _web_create(web_client, name="还清信用卡", debt_ids=[a["public_id"]], key=key)
    replay = _web_create(web_client, name="还清信用卡", debt_ids=[a["public_id"]], key=key)

    assert first.status_code == 303
    assert replay.status_code == 303  # 重放返回 canonical 结果，不建第二个目标
    goals = web_client.get("/api/goals?goal_type=debt_repayment", headers=identity.app_headers).json()["items"]
    assert [g["name"] for g in goals] == ["还清信用卡"]  # 重放没有建第二个目标
    html = _page(web_client)
    assert "已还清 0 / 1 笔" in html


def test_create_validation_rerenders_422_preserving_values(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    _create_external_debt(web_client, identity.app_headers, principal_amount_cents=20000)
    key = str(uuid4())

    resp = _web_create(web_client, name="  ", debt_ids=[a["public_id"]], key=key)

    assert resp.status_code == 422
    assert "请输入目标名称并至少选择一笔未结清欠款。" in resp.text
    assert f'value="{key}"' in resp.text  # 保留已提交键：重试仍命中同一 claim
    assert f'value="{a["public_id"]}"' in resp.text and "checked" in resp.text  # 勾选被回填
    assert "新建还债目标" in resp.text  # 原地重渲染，不是裸错页


def test_create_empty_selection_rerenders_422(web_client: TestClient, *, identity) -> None:
    _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    resp = _web_create(web_client, name="没有勾选", debt_ids=[])
    assert resp.status_code == 422
    assert "请输入目标名称并至少选择一笔未结清欠款。" in resp.text
    assert 'value="没有勾选"' in resp.text  # 名字回填


# ── links ────────────────────────────────────────────────────────────────────
def test_links_replace_idempotent_replay(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="扩关联", debt_public_ids=[a["public_id"]]
    ).json()
    key = str(uuid4())

    first = _web_links(
        web_client, goal["public_id"], row_version=goal["row_version"], debt_ids=[a["public_id"], b["public_id"]], key=key
    )
    replay = _web_links(
        web_client, goal["public_id"], row_version=goal["row_version"], debt_ids=[a["public_id"], b["public_id"]], key=key
    )

    assert first.status_code == 303
    assert replay.status_code == 303
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["goal_version"] == 2  # 重放没有再撞版本
    assert _links_count_for_version(goal["public_id"], 2) == 2
    assert _links_count_for_version(goal["public_id"], 3) == 0


def test_links_stale_occ_redirects_with_stale_message(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="过期快照", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_links(
        web_client,
        goal["public_id"],
        row_version=goal["row_version"] + 9,  # 过期 OCC 快照
        debt_ids=[a["public_id"], b["public_id"]],
    )

    assert _redirect_error(resp) == _STALE
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["goal_version"] == 1  # 未写
    assert current["row_version"] == goal["row_version"]


def test_links_empty_selection_rerenders_422_preserving_checkboxes(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="不能清空", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_links(web_client, goal["public_id"], row_version=goal["row_version"], debt_ids=[])

    assert resp.status_code == 422
    assert "至少选择一笔欠款" in resp.text or "至少需要关联一笔欠款" in resp.text
    assert "不能清空" in resp.text  # 原地重渲染
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["debt_repayment"]["goal_version"] == 1


# ── target-date ──────────────────────────────────────────────────────────────
def test_target_date_set_and_clear_round_trip(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="定日期", debt_public_ids=[a["public_id"]]
    ).json()

    set_resp = _web_goal_post(
        web_client, goal["public_id"], "target-date",
        row_version=goal["row_version"], extra={"target_date": "2027-05-01"},
    )
    assert set_resp.status_code == 303
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["target_date"] == "2027-05-01"

    clear_resp = _web_goal_post(
        web_client, goal["public_id"], "target-date",
        row_version=current["row_version"], extra={"target_date": ""},
    )
    assert clear_resp.status_code == 303
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["debt_repayment"]["target_date"] is None


def test_target_date_stale_occ_redirects(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="日期冲突", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_goal_post(
        web_client, goal["public_id"], "target-date",
        row_version=goal["row_version"] + 9, extra={"target_date": "2027-05-01"},
    )

    assert _redirect_error(resp) == _STALE
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["debt_repayment"]["target_date"] is None


def test_target_date_invalid_rerenders_422_preserving_value(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="坏日期", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_goal_post(
        web_client, goal["public_id"], "target-date",
        row_version=goal["row_version"], extra={"target_date": "not-a-date"},
    )

    assert resp.status_code == 422
    assert "请选择正确的还清日期。" in resp.text
    assert 'value="not-a-date"' in resp.text  # 已填值回填


# ── review/acknowledge + review/remove-voided ────────────────────────────────
def _seed_achieved_goal_with_voided_link(web_client: TestClient, headers: dict[str, str]) -> tuple[dict, dict]:
    """一个已达成目标随后作废旧联欠款 → achieved + needs_review (保留存档臂)。"""
    a = _create_external_debt(web_client, headers, principal_amount_cents=10000)
    goal = _create_debt_goal(web_client, headers, name="保留存档", debt_public_ids=[a["public_id"]]).json()
    cleared = _clear_debt(web_client, headers, a)
    web_client.get(f"/api/goals/{goal['public_id']}", headers=headers)  # latch achieved
    _void_debt(web_client, headers, cleared)
    current = _goal_view(web_client, headers, goal["public_id"])
    assert current["debt_repayment"]["evaluation_state"] == "achieved"
    assert current["debt_repayment"]["needs_review"] is True
    return current, a


def test_review_acknowledge_happy_and_idempotent_replay(web_client: TestClient, *, identity) -> None:
    goal, _ = _seed_achieved_goal_with_voided_link(web_client, identity.app_headers)
    key = str(uuid4())

    first = _web_goal_post(web_client, goal["public_id"], "review/acknowledge", row_version=goal["row_version"], key=key)
    replay = _web_goal_post(web_client, goal["public_id"], "review/acknowledge", row_version=goal["row_version"], key=key)

    assert first.status_code == 303
    assert replay.status_code == 303
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["needs_review"] is False
    assert current["debt_repayment"]["evaluation_state"] == "achieved"  # 确认不撤销达成


def test_review_acknowledge_422_arm_redirects(web_client: TestClient, *, identity) -> None:
    # 未达成且无作废 → 没有待确认的复核 → 422 arm → 303 带回错误，不写。
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="无需复核", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_goal_post(web_client, goal["public_id"], "review/acknowledge", row_version=goal["row_version"])

    assert _redirect_error(resp) == "没有待确认的债务作废复核（目标须已达成且有被作废的关联欠款）。"
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["row_version"] == goal["row_version"]


def test_review_remove_voided_happy_and_idempotent_replay(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    b = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=20000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="移除作废", debt_public_ids=[a["public_id"], b["public_id"]]
    ).json()
    _void_debt(web_client, identity.app_headers, a)
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["needs_review"] is True
    key = str(uuid4())

    first = _web_goal_post(
        web_client, goal["public_id"], "review/remove-voided", row_version=current["row_version"], key=key
    )
    replay = _web_goal_post(
        web_client, goal["public_id"], "review/remove-voided", row_version=current["row_version"], key=key
    )

    assert first.status_code == 303
    assert replay.status_code == 303
    after = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert after["debt_repayment"]["goal_version"] == 2  # 重放没有再撞版本
    assert after["debt_repayment"]["needs_review"] is False
    assert [link["debt_public_id"] for link in after["debt_repayment"]["linked_debts"]] == [b["public_id"]]


def test_review_remove_voided_arm_not_needs_review(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="不需复核", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_goal_post(web_client, goal["public_id"], "review/remove-voided", row_version=goal["row_version"])

    assert _redirect_error(resp) == "这个目标目前不需要复核。"
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["debt_repayment"]["goal_version"] == 1


def test_review_remove_voided_arm_nothing_left(web_client: TestClient, *, identity) -> None:
    # 全部关联欠款都作废 → 没有可保留的有效欠款 → 422 arm (提示可归档)，不撞版本。
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="全作废", debt_public_ids=[a["public_id"]]
    ).json()
    _void_debt(web_client, identity.app_headers, a)
    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    assert current["debt_repayment"]["needs_review"] is True

    resp = _web_goal_post(
        web_client, goal["public_id"], "review/remove-voided", row_version=current["row_version"]
    )

    assert _redirect_error(resp) == "至少需要保留一笔有效欠款；也可以把目标归档。"
    assert _goal_view(web_client, identity.app_headers, goal["public_id"])["debt_repayment"]["goal_version"] == 1


# ── archive / restore ────────────────────────────────────────────────────────
def test_archive_restore_round_trip_with_replays(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="归档再恢复", debt_public_ids=[a["public_id"]]
    ).json()
    archive_key = str(uuid4())

    archived = _web_goal_post(
        web_client, goal["public_id"], "archive", row_version=goal["row_version"], key=archive_key
    )
    assert archived.status_code == 303
    replay = _web_goal_post(
        web_client, goal["public_id"], "archive", row_version=goal["row_version"], key=archive_key
    )
    assert replay.status_code == 303  # 重放不二次归档报错
    assert _goal_row(goal["public_id"]).status == "archived"

    html = _page(web_client)
    assert "已归档计划" in html  # 归档区出现
    assert f"/web/debt-goals/{goal['public_id']}/restore" in html

    current = _goal_view(web_client, identity.app_headers, goal["public_id"])
    restore_key = str(uuid4())
    restored = _web_goal_post(
        web_client, goal["public_id"], "restore", row_version=current["row_version"], key=restore_key
    )
    assert restored.status_code == 303
    restore_replay = _web_goal_post(
        web_client, goal["public_id"], "restore", row_version=current["row_version"], key=restore_key
    )
    assert restore_replay.status_code == 303  # 重放返回 canonical，不报错
    assert _goal_row(goal["public_id"]).status == "active"


def test_archive_stale_occ_redirects(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    goal = _create_debt_goal(
        web_client, identity.app_headers, name="归档冲突", debt_public_ids=[a["public_id"]]
    ).json()

    resp = _web_goal_post(
        web_client, goal["public_id"], "archive", row_version=goal["row_version"] + 9
    )

    assert _redirect_error(resp) == _STALE
    assert _goal_row(goal["public_id"]).status == "active"


# ── viewer gating ────────────────────────────────────────────────────────────
def test_viewer_gets_no_forms_and_post_is_denied(web_client: TestClient, *, identity) -> None:
    a = _create_external_debt(web_client, identity.app_headers, principal_amount_cents=10000)
    _create_debt_goal(web_client, identity.app_headers, name="只读可见", debt_public_ids=[a["public_id"]])
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").order_by(LedgerMember.id.asc()).limit(1)
        )
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    html = _page(web_client)
    assert "只读可见" in html  # 目标仍可读
    assert "<form" not in html  # 只读角色无任何表单
    assert 'name="expected_row_version"' not in html
    assert "只读角色可以查看还债目标" in html

    denied = _web_create(web_client, name="不允许", debt_ids=[a["public_id"]])
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"
