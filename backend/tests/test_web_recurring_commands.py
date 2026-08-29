"""Command tests for /web recurring: mutation journeys with DB postconditions.

Page render / error-surface assertions live in test_web_recurring.py.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from _web_recurring_test_support import (
    create_via_web,
    edit_via_web,
    extract_hidden_token,
    post_confirm,
    row_version,
    seed_candidate,
    seed_observed_item,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import RecurringItem
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_web_recurring_create_persists_manual_item(web_client: TestClient) -> None:
    created = create_via_web(web_client, merchant="房租", amount="6800", date_str="2026-09-06")
    assert created.status_code == 303

    with SessionLocal() as db:
        item = db.scalar(
            select(RecurringItem).where(RecurringItem.merchant_name == "房租")
        )
        assert item is not None
        assert item.source == "manual"
        assert item.frequency == "monthly"
        assert item.occurrence_count == 0
        assert item.status == "active"
        assert item.baseline_amount_cents == 680_000
        assert item.next_expected_date == date(2026, 9, 6)


def test_web_recurring_create_replays_same_idempotency_key(web_client: TestClient) -> None:
    """同一表单 intent (同一 Idempotency-Key) 的 durable replay: 只建一条。"""
    key = str(uuid4())
    assert create_via_web(web_client, key=key).status_code == 303
    assert create_via_web(web_client, key=key).status_code == 303
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.merchant_name == "房租")
        )
        assert count == 1


def test_web_recurring_edit_updates_expectation_and_preserves_observation(
    web_client: TestClient,
) -> None:
    """PATCH 只改用户预计 (merchant/baseline/next date), 绝不触碰观察事实。"""
    public_id = seed_observed_item()
    token = row_version(public_id)
    with SessionLocal() as db:
        last_seen = db.scalar(
            select(RecurringItem.last_seen_at).where(RecurringItem.public_id == public_id)
        )
    assert last_seen is not None

    edited = edit_via_web(web_client, public_id, token=token)

    assert edited.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "Cloud Storage 家庭版"
        assert item.baseline_amount_cents == 2_500
        assert item.next_expected_date == date(2026, 10, 8)
        # 观察来源原样保留。
        assert item.last_amount_cents == 1_900
        assert item.occurrence_count == 5
        assert item.last_seen_at == last_seen
        assert item.source == "candidate"
        assert item.confidence == "high"
        assert item.row_version == token + 1


def test_web_recurring_edit_clears_next_date(web_client: TestClient) -> None:
    """日期可清空 = 显式 null: 清空后不再提醒。"""
    public_id = seed_observed_item()

    edited = edit_via_web(web_client, public_id, date_str="", token=row_version(public_id))

    assert edited.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.next_expected_date is None
    page = web_client.get("/web/recurring?ledger_id=owner")
    assert "不提醒" in page.text


def test_web_recurring_edit_replays_same_idempotency_key(web_client: TestClient) -> None:
    """committed-but-unseen: 同一 intent key + 同一 (stale) token 重放,
    返回成功而不是 false-409, 且不二次推进 row_version。"""
    public_id = seed_observed_item()
    token = row_version(public_id)
    key = str(uuid4())

    assert edit_via_web(web_client, public_id, token=token, key=key).status_code == 303
    assert edit_via_web(web_client, public_id, token=token, key=key).status_code == 303

    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "Cloud Storage 家庭版"
        assert item.row_version == token + 1


def test_web_recurring_candidate_confirm_uses_server_side_provenance(
    web_client: TestClient,
) -> None:
    """候选提交只定位 merchant + amount: occurrence_count / last_seen_at /
    confidence 一律取当前服务端候选扫描, 客户端伪造值必须被忽略;
    source=candidate 等观察事实保留; 采用后候选消失。"""
    seed_candidate()

    adopted = post_confirm(
        web_client,
        next_expected_date="2026-10-05",
        # 伪造的客户端 provenance — 路由不接收, service 不信任。
        occurrence_count="99",
        confidence="bogus",
        last_seen_at="1999-01-01T00:00:00Z",
    )
    assert adopted.status_code == 303

    with SessionLocal() as db:
        item = db.scalar(
            select(RecurringItem).where(RecurringItem.merchant_name == "ChatGPT Plus")
        )
        assert item is not None
        assert item.source == "candidate"
        assert item.occurrence_count == 3
        assert item.confidence
        assert item.confidence != "bogus"
        assert item.last_seen_at is not None
        assert item.last_seen_at.year != 1999
        assert item.baseline_amount_cents == 20000
        assert item.next_expected_date == date(2026, 10, 5)

    after = web_client.get("/web/recurring?ledger_id=owner")
    assert after.status_code == 200
    assert "复核采用" not in after.text


def test_web_recurring_confirm_retry_returns_existing_not_error(web_client: TestClient) -> None:
    """PR #253 R4-2 幂等: 候选消失后重试同一确认, 返回既有正式项而非 404/409。"""
    seed_candidate()
    assert post_confirm(web_client).status_code == 303
    assert post_confirm(web_client).status_code == 303
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.merchant_name == "ChatGPT Plus")
        )
        assert count == 1


def test_web_recurring_pause_resume_archive_use_rendered_token(web_client: TestClient) -> None:
    """ADR-0038 PR-A regression: pause/resume 表单必须渲染真实 OCC token;
    完整状态循环 pause → resume → archive 均可用。"""
    public_id = seed_observed_item()

    page = web_client.get("/web/recurring?ledger_id=owner")
    token = extract_hidden_token(page.text, action=f"/web/recurring/{public_id}/pause")
    assert token, "pause form must render a non-empty expected_row_version token"
    paused = web_client.post(
        f"/web/recurring/{public_id}/pause",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert paused.status_code == 303
    with SessionLocal() as db:
        assert (
            db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id))
            == "paused"
        )

    page = web_client.get("/web/recurring?ledger_id=owner")
    token = extract_hidden_token(page.text, action=f"/web/recurring/{public_id}/resume")
    assert token, "resume form must render a non-empty expected_row_version token"
    resumed = web_client.post(
        f"/web/recurring/{public_id}/resume",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert resumed.status_code == 303

    archived = web_client.post(
        f"/web/recurring/{public_id}/archive",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert archived.status_code == 303
    with SessionLocal() as db:
        assert (
            db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id))
            == "archived"
        )


def test_web_recurring_restore_archived_item(web_client: TestClient) -> None:
    """默认「全部」不混入归档尸体; 归档筛选里的恢复入口 (OCC) 恢复后回到默认列表。"""
    public_id = seed_observed_item(status="archived")

    default_page = web_client.get("/web/recurring?ledger_id=owner")
    assert "Cloud Storage" not in default_page.text

    page = web_client.get("/web/recurring?ledger_id=owner&status=archived")
    assert page.status_code == 200
    token = extract_hidden_token(page.text, action=f"/web/recurring/{public_id}/restore")
    assert token, "restore form must render a non-empty expected_row_version token"

    restored = web_client.post(
        f"/web/recurring/{public_id}/restore",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    with SessionLocal() as db:
        status = db.scalar(
            select(RecurringItem.status).where(RecurringItem.public_id == public_id)
        )
        assert status == "active"
    default_page = web_client.get("/web/recurring?ledger_id=owner")
    assert "Cloud Storage" in default_page.text


# ── confirm service 语义守护 (本页真实消费者依赖的契约) ───────────────────────


def test_confirm_retry_with_different_amount_points_to_existing_item(
    web_client: TestClient,
) -> None:
    """Same candidate replay is idempotent; a changed amount is an edit conflict."""
    from app.errors import AppError
    from app.schemas import RecurringCandidateConfirmRequest
    from app.services.recurring_candidate_confirmation_service import confirm_recurring_candidate

    seed_candidate()
    with SessionLocal() as db:
        created = confirm_recurring_candidate(
            db,
            tenant_id="owner",
            payload=RecurringCandidateConfirmRequest(
                merchant="ChatGPT Plus",
                amount_cents=20000,
                frequency="monthly",
            ),
        )
        db.commit()
        # 同金额重试: 幂等返回既有项。
        same = confirm_recurring_candidate(
            db,
            tenant_id="owner",
            payload=RecurringCandidateConfirmRequest(
                merchant="ChatGPT Plus",
                amount_cents=20000,
                frequency="monthly",
            ),
        )
        assert same.id == created.id
        # A changed amount is a new intent against the same formal item. Point
        # the consumer to that item instead of pretending the candidate vanished.
        try:
            confirm_recurring_candidate(
                db,
                tenant_id="owner",
                payload=RecurringCandidateConfirmRequest(
                    merchant="ChatGPT Plus",
                    amount_cents=21000,
                    frequency="monthly",
                ),
            )
            raise AssertionError("different-amount retry must not silently return the formal item")
        except AppError as exc:
            assert exc.error == "recurring_item_conflict"
            assert exc.status_code == 409
            assert exc.details == {"public_id": created.public_id, "status": "active"}


def test_confirm_candidate_race_returns_existing_after_candidate_disappears(
    web_client: TestClient, monkeypatch
) -> None:
    """PR #253 R5: 并发双请求——前置检查读到提交前快照, candidate 已被对方 claimed
    过滤时, 按 (merchant_key, frequency, amount_cents) 复查 formal 幂等返回。"""
    from app.schemas import RecurringCandidateConfirmRequest
    from app.services import recurring_candidate_confirmation_service as confirmation
    from app.services.recurring_candidate_confirmation_service import confirm_recurring_candidate

    seed_candidate()
    payload = RecurringCandidateConfirmRequest(
        merchant="ChatGPT Plus",
        amount_cents=20000,
        frequency="monthly",
    )
    with SessionLocal() as db:
        first = confirm_recurring_candidate(db, tenant_id="owner", payload=payload)
        db.commit()

        # 模拟请求 B: 第一次 _existing_item 调用 (前置检查) 返回 None —— 即读到
        # 请求 A 提交前的快照; 随后 candidate 查找已被 claimed 过滤 (not_found)。
        calls = {"n": 0}
        real_existing = confirmation._existing_item

        def _stale_existing(db, *, tenant_id, merchant_key, frequency):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return real_existing(
                db, tenant_id=tenant_id, merchant_key=merchant_key, frequency=frequency
            )

        monkeypatch.setattr(confirmation, "_existing_item", _stale_existing)
        second = confirm_recurring_candidate(db, tenant_id="owner", payload=payload)
        assert second.id == first.id
        # 路径证明: 确实走了兜底 (前置检查返回过 None)。
        assert calls["n"] >= 2
