"""Tests for /web recurring management page."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember, RecurringItem
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _seed_candidate() -> None:
    for when in (
        datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
        datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
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
            "last_seen_at": "2026-05-05T12:00:00Z",
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


def test_web_recurring_confirm_pause_resume_archive(web_client: TestClient) -> None:
    _seed_candidate()
    page = web_client.get("/web/recurring?ledger_id=owner")
    assert page.status_code == 200

    _confirm_candidate(web_client)

    public_id = _first_recurring_public_id()
    paused = web_client.post(
        f"/web/recurring/{public_id}/pause",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert paused.status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(RecurringItem.status).where(RecurringItem.public_id == public_id)) == "paused"

    resumed = web_client.post(
        f"/web/recurring/{public_id}/resume",
        data={"ledger_id": "owner"},
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


def test_web_stats_distinguishes_formal_recurring_from_candidates(web_client: TestClient) -> None:
    _seed_candidate()
    before = web_client.get("/web")
    assert before.status_code == 200
    assert "正式固定支出" in before.text
    assert "1 个候选未确认" in before.text

    _confirm_candidate(web_client)

    stats = web_client.get("/web/stats?ledger_id=owner&month=2026-05")
    assert stats.status_code == 200
    assert "正式固定支出" in stats.text
    assert "固定支出候选（未确认）" in stats.text
    assert "ChatGPT Plus" in stats.text
    assert "只做提醒和对比，不会自动入账" in stats.text


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
