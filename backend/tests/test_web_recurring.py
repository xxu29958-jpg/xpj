"""Tests for /web recurring management page."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember, RecurringItem
from app.routes.web_app import _require_local as _web_require_local
from app.services.time_service import now_utc


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _seed_candidate() -> None:
    # PR #253 R4: 候选扫描窗口为近 6 个月, 播种改相对日期 (固定日期会随时间掉出窗口)。
    base = now_utc()
    for when in (
        base - timedelta(days=62),
        base - timedelta(days=31),
        base,
    ):
        insert_confirmed_expense(
            amount_cents=20000,
            merchant="ChatGPT Plus",
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()


def _first_recurring_public_id() -> str:
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).limit(1))
        assert item is not None
        return item.public_id


def _confirm_candidate(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/recurring/confirm-candidate",
        data={
            "ledger_id": "owner",
            "merchant": "ChatGPT Plus",
            "amount_cents": "20000",
            "occurrence_count": "3",
            "last_seen_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "confidence": "high",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_web_recurring_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/recurring").status_code == 403
    assert client.post("/web/recurring/confirm-candidate").status_code == 403


def test_web_recurring_renders_candidates(web_client: TestClient) -> None:
    _seed_candidate()

    response = web_client.get("/web/recurring?ledger_id=owner")

    assert response.status_code == 200
    assert "固定支出" in response.text
    assert "ChatGPT Plus" in response.text
    assert "候选" in response.text
    assert "确认" in response.text


def test_web_recurring_candidate_insight_failure_degrades(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Coverage migrated from the deleted /web/stats page: the candidate
    # insight blowing up must degrade to an inline notice, never 500.
    from app.routes import web_recurring as web_recurring_module

    def fail_recurring_candidates(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_recurring_module, "recurring_candidates", fail_recurring_candidates)

    resp = web_client.get("/web/recurring?ledger_id=owner")

    assert resp.status_code == 200
    assert "固定支出候选分析暂时不可用" in resp.text


def test_web_recurring_confirm_pause_resume_archive(web_client: TestClient) -> None:
    _seed_candidate()
    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200

    _confirm_candidate(web_client)

    public_id = _first_recurring_public_id()
    # ADR-0038 PR-A: pause/resume need OCC token (banner-render time updated_at)
    with SessionLocal() as db:
        token = db.scalar(
            select(RecurringItem.row_version).where(RecurringItem.public_id == public_id)
        )
    paused = web_client.post(
        f"/web/recurring/{public_id}/pause",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert paused.status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id)) == "paused"
        token = db.scalar(
            select(RecurringItem.row_version).where(RecurringItem.public_id == public_id)
        )

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
        assert db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id)) == "archived"


def test_web_recurring_distinguishes_formal_recurring_from_candidates(web_client: TestClient) -> None:
    # UI/UX 批 14: /web/stats 页删除,固定支出表是 /web/recurring 的严格子集,未迁移;
    # 「正式 vs 候选」区分改在 /web/recurring 页守护(dashboard 摘要不变)。
    _seed_candidate()
    before = web_client.get("/web")
    assert before.status_code == 200
    assert "正式固定支出" in before.text
    assert "1 个候选未确认" in before.text

    _confirm_candidate(web_client)

    recurring = web_client.get("/web/recurring?ledger_id=owner")
    assert recurring.status_code == 200
    assert "正式固定支出" in recurring.text
    assert "固定支出候选（未确认）" in recurring.text
    assert "ChatGPT Plus" in recurring.text
    assert "只做提醒和对比，不会自动入账" in recurring.text


def test_web_recurring_viewer_read_only(web_client: TestClient) -> None:
    _seed_candidate()
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200
    assert "只读角色" in page.text
    assert "/web/recurring/confirm-candidate" not in page.text

    denied = web_client.post(
        "/web/recurring/confirm-candidate",
        data={
            "ledger_id": "owner",
            "merchant": "ChatGPT Plus",
            "amount_cents": "20000",
            "occurrence_count": "3",
            "last_seen_at": "2026-05-05T12:00:00Z",
            "confidence": "high",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"


def _extract_hidden_token(html: str, *, action: str) -> str:
    """Pull ``expected_row_version`` out of the form whose ``action`` matches —
    i.e. the token as actually rendered into the page, not a value read
    straight from the DB. Returns "" when absent so the caller can assert the
    page emits a real token."""
    form = re.search(re.escape(f'action="{action}"') + r".*?</form>", html, re.DOTALL)
    if not form:
        return ""
    field = re.search(r'name="expected_row_version"\s+value="([^"]*)"', form.group(0))
    return field.group(1) if field else ""


def test_web_recurring_pause_resume_use_rendered_token(web_client: TestClient) -> None:
    """ADR-0038 PR-A regression (codex P1#2). The pause/resume forms must carry
    a real OCC token *rendered into the page*. ``_item_view`` previously omitted
    ``updated_at`` so the hidden field rendered empty → parse_form_row_version_token
    returned None → every web user hit the "页面已过期" redirect and could never
    toggle. Driving the token from the rendered HTML (not a DB read like the
    sibling test) fails if the page stops emitting it."""
    _seed_candidate()
    _confirm_candidate(web_client)
    public_id = _first_recurring_public_id()

    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200
    token = _extract_hidden_token(page.text, action=f"/web/recurring/{public_id}/pause")
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
    token = _extract_hidden_token(page.text, action=f"/web/recurring/{public_id}/resume")
    assert token, "resume form must render a non-empty expected_row_version token"

    resumed = web_client.post(
        f"/web/recurring/{public_id}/resume",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert resumed.status_code == 303
    with SessionLocal() as db:
        assert (
            db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id))
            == "active"
        )


def test_web_recurring_candidate_disappears_after_confirm(web_client: TestClient) -> None:
    """PR #253 R4-2: claimed 过滤下推共享装配后, 已转正商家从候选列表自然消失。"""
    _seed_candidate()
    before = web_client.get("/web/recurring?ledger_id=owner")
    assert before.status_code == 200
    assert 'action="/web/recurring/confirm-candidate"' in before.text

    _confirm_candidate(web_client)

    after = web_client.get("/web/recurring?ledger_id=owner")
    assert after.status_code == 200
    # 正式列表仍在, 候选确认表单不再出现 (候选集已空)。
    assert "ChatGPT Plus" in after.text
    assert 'action="/web/recurring/confirm-candidate"' not in after.text


def test_web_recurring_confirm_retry_returns_existing_not_error(web_client: TestClient) -> None:
    """PR #253 R4-2 幂等: 候选消失后重试同一确认, 返回既有正式项而非 404/409。"""
    _seed_candidate()
    _confirm_candidate(web_client)
    # 重试同一确认 payload — 候选已被 claimed 过滤, 幂等前置返回既有项。
    retry = web_client.post(
        "/web/recurring/confirm-candidate",
        data={
            "ledger_id": "owner",
            "merchant": "ChatGPT Plus",
            "amount_cents": "20000",
            "occurrence_count": "3",
            "last_seen_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "confidence": "high",
        },
        follow_redirects=False,
    )
    assert retry.status_code == 303
    with SessionLocal() as db:
        items = list(
            db.scalars(
                select(RecurringItem)
                .where(RecurringItem.tenant_id == "owner")
                .where(RecurringItem.merchant_name == "ChatGPT Plus")
            ).all()
        )
        assert len(items) == 1


def test_confirm_retry_with_different_amount_restores_not_found_guard(
    web_client: TestClient,
) -> None:
    """复审 agent-60: 已 formal 商家以不同金额重试 → 恢复 404 守卫; 同金额 → 幂等返回。"""
    from app.errors import AppError
    from app.schemas import RecurringCandidateConfirmRequest
    from app.services.recurring_candidate_confirmation_service import confirm_recurring_candidate

    _seed_candidate()
    with SessionLocal() as db:
        created = confirm_recurring_candidate(
            db,
            tenant_id="owner",
            payload=RecurringCandidateConfirmRequest(
                merchant="ChatGPT Plus",
                amount_cents=20000,
                occurrence_count=3,
                last_seen_at=now_utc(),
                confidence="high",
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
                occurrence_count=3,
                last_seen_at=now_utc(),
                confidence="high",
                frequency="monthly",
            ),
        )
        assert same.id == created.id
        # 不同金额重试: 恢复候选匹配的 404 守卫, 不静默返回既有项。
        try:
            confirm_recurring_candidate(
                db,
                tenant_id="owner",
                payload=RecurringCandidateConfirmRequest(
                    merchant="ChatGPT Plus",
                    amount_cents=21000,
                    occurrence_count=3,
                    last_seen_at=now_utc(),
                    confidence="high",
                    frequency="monthly",
                ),
            )
            raise AssertionError("different-amount retry must not silently return the formal item")
        except AppError as exc:
            assert exc.error == "recurring_candidate_not_found"
            assert exc.status_code == 404
