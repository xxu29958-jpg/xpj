"""Command tests for /web recurring: mutation journeys with DB postconditions.

Page render / error-surface assertions live in test_web_recurring.py.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import unquote
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
    """PATCH 可改 baseline/next date，绝不触碰观察身份与 provenance。"""
    public_id = seed_observed_item()
    token = row_version(public_id)
    with SessionLocal() as db:
        last_seen = db.scalar(
            select(RecurringItem.last_seen_at).where(RecurringItem.public_id == public_id)
        )
    assert last_seen is not None

    edited = edit_via_web(web_client, public_id, merchant="Cloud Storage", token=token)

    assert edited.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "Cloud Storage"
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

    edited = edit_via_web(
        web_client,
        public_id,
        merchant="Cloud Storage",
        date_str="",
        token=row_version(public_id),
    )

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

    assert edit_via_web(
        web_client,
        public_id,
        merchant="Cloud Storage",
        token=token,
        key=key,
    ).status_code == 303
    assert edit_via_web(
        web_client,
        public_id,
        merchant="Cloud Storage",
        token=token,
        key=key,
    ).status_code == 303

    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "Cloud Storage"
        assert item.row_version == token + 1


# ── 输入类错误的 attempt@baseline: 草稿携带 submitted token, 世界仲裁留给 backend ──


def test_web_recurring_edit_input_error_echoes_attempt_baseline_then_occ_arbitrates(
    web_client: TestClient,
) -> None:
    """精确交错回归: GET 时拿到 token7 → 另一消费者推进到 rv8 → 用户仍持 token7
    提交非法金额 (route 级 parse 失败, 未进 service/OCC)。错误页必须回声完整草稿
    与原 token7 — 不得把 hidden expected_row_version 升级为 rv8, 否则修正后重提
    会带着从未见过的 baseline 通过 OCC, 静默覆盖远端字段。修正金额后以新 intent
    key 重提 → backend 仲裁判 state_conflict, rv8 不变, 页面只回 server truth。"""
    public_id = seed_observed_item(merchant="房租", occurrence_count=0, source="manual")
    stale_token = row_version(public_id)

    # 另一消费者的合法编辑把条目推进到下一 row_version。
    advanced = edit_via_web(web_client, public_id, merchant="房租", amount="7000", token=stale_token)
    assert advanced.status_code == 303
    remote_token = row_version(public_id)
    assert remote_token == stale_token + 1

    # 用户仍持旧 token 提交非法金额: 输入类错误页回声完整草稿 + 原 baseline token。
    rejected = edit_via_web(web_client, public_id, merchant="房租（自住）", amount="abc", token=stale_token)
    assert rejected.status_code == 200
    assert "每月金额不是合法金额" in rejected.text
    assert extract_hidden_token(rejected.text, action=f"/web/recurring/{public_id}/edit") == str(stale_token)
    form = re.search(
        rf'<details class="rc-edit" open>.*?action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        rejected.text,
        re.DOTALL,
    )
    assert form is not None, "input-error render must keep the edit form open with the draft"
    assert 'value="房租（自住）"' in form.group(0)
    assert 'value="abc"' in form.group(0)

    # 修正金额、新 intent key 重提: OCC 仲裁 → state_conflict; rv8 原样, 草稿丢弃,
    # 表单回到服务端事实 (merchant 与 token 均为远端当前值)。
    retried = edit_via_web(web_client, public_id, merchant="房租（自住）", amount="7200", token=stale_token)
    assert retried.status_code == 200
    assert "请核对后再保存" in retried.text
    assert "房租（自住）" not in retried.text
    assert extract_hidden_token(retried.text, action=f"/web/recurring/{public_id}/edit") == str(remote_token)
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.row_version == remote_token
        assert item.merchant_name == "房租"
        assert item.baseline_amount_cents == 700_000


def test_web_recurring_edit_input_error_is_correctable_in_place(web_client: TestClient) -> None:
    """无漂移常态: 输入类错误回声草稿且 token 即当前 row_version, 就地修正后保存成功。"""
    public_id = seed_observed_item(occurrence_count=0, source="manual")
    token = row_version(public_id)

    rejected = edit_via_web(web_client, public_id, merchant="物业费", amount="", token=token)
    assert rejected.status_code == 200
    assert "请填写每月金额" in rejected.text
    assert extract_hidden_token(rejected.text, action=f"/web/recurring/{public_id}/edit") == str(token)
    form = re.search(
        rf'<details class="rc-edit" open>.*?action="/web/recurring/{re.escape(public_id)}/edit".*?</form>',
        rejected.text,
        re.DOTALL,
    )
    assert form is not None
    assert 'value="物业费"' in form.group(0)

    fixed = edit_via_web(web_client, public_id, merchant="物业费", amount="300", token=token)
    assert fixed.status_code == 303
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert item is not None
        assert item.merchant_name == "物业费"
        assert item.baseline_amount_cents == 30_000
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


def test_web_recurring_stale_restore_never_reports_a_later_pause_as_active(
    web_client: TestClient,
) -> None:
    public_id = seed_observed_item(status="archived")
    restore_token = row_version(public_id)
    restored = web_client.post(
        f"/web/recurring/{public_id}/restore",
        data={"ledger_id": "owner", "expected_row_version": str(restore_token)},
        follow_redirects=False,
    )
    assert restored.status_code == 303

    active_page = web_client.get("/web/recurring?ledger_id=owner")
    pause_token = extract_hidden_token(
        active_page.text,
        action=f"/web/recurring/{public_id}/pause",
    )
    assert pause_token
    paused = web_client.post(
        f"/web/recurring/{public_id}/pause",
        data={"ledger_id": "owner", "expected_row_version": pause_token},
        follow_redirects=False,
    )
    assert paused.status_code == 303

    stale_restore = web_client.post(
        f"/web/recurring/{public_id}/restore",
        data={"ledger_id": "owner", "expected_row_version": str(restore_token)},
        follow_redirects=False,
    )
    assert stale_restore.status_code == 303
    location = unquote(stale_restore.headers["location"])
    assert "页面已过期，请刷新后重新操作。" in location
    assert "已恢复为活跃。" not in location
    with SessionLocal() as db:
        status = db.scalar(
            select(RecurringItem.status).where(RecurringItem.public_id == public_id)
        )
        assert status == "paused"


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


@pytest.mark.real_db
def test_confirm_candidate_insert_race_returns_one_shared_fact(
    web_client: TestClient,
    monkeypatch,
) -> None:
    """Two real PG sessions may both pass projection/precheck before the unique insert."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.schemas import RecurringCandidateConfirmRequest
    from app.services import recurring_candidate_confirmation_service as confirmation

    seed_candidate()
    payload = RecurringCandidateConfirmRequest(
        merchant="ChatGPT Plus",
        amount_cents=20000,
        frequency="monthly",
    )
    barrier = Barrier(2)
    real_create = confirmation._create_recurring_item_from_candidate

    def synchronized_create(*args, **kwargs):
        barrier.wait(timeout=10)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(
        confirmation,
        "_create_recurring_item_from_candidate",
        synchronized_create,
    )

    def confirm(_: int) -> int:
        with SessionLocal() as db:
            item = confirmation.confirm_recurring_candidate(
                db,
                tenant_id="owner",
                payload=payload,
            )
            return item.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(confirm, range(2), timeout=15))

    assert len(ids) == 2
    assert len(set(ids)) == 1
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
            .where(RecurringItem.merchant_key == "chatgpt plus")
        )
        assert count == 1
