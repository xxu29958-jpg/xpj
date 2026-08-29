"""Shared helpers for the /web recurring test files.

The ``web_client`` fixture stays defined per test file (repo convention); this
module only holds seed/post/extract helpers.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from uuid import uuid4

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember, RecurringItem
from app.services.currency_binding_service import resolve_write_capability
from app.services.insights_service import normalize_merchant
from app.services.time_service import now_utc


def seed_candidate() -> None:
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


def seed_observed_item(
    *,
    merchant: str = "Cloud Storage",
    baseline_cents: int = 2_000,
    last_cents: int = 1_900,
    occurrence_count: int = 5,
    status: str = "active",
    next_date: date | None = date(2026, 9, 8),
) -> str:
    """Seed a candidate-sourced formal item with real observation provenance."""
    now = now_utc()
    with SessionLocal() as db:
        resolve_write_capability(db)
        item = RecurringItem(
            tenant_id="owner",
            merchant_key=normalize_merchant(merchant),
            merchant_name=merchant,
            frequency="monthly",
            baseline_amount_cents=baseline_cents,
            last_amount_cents=last_cents,
            occurrence_count=occurrence_count,
            last_seen_at=now,
            next_expected_date=next_date,
            status=status,
            confidence="high",
            source="candidate",
            created_at=now,
            updated_at=now,
            archived_at=now if status == "archived" else None,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item.public_id


def demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()


def first_recurring_public_id() -> str:
    with SessionLocal() as db:
        item = db.scalar(select(RecurringItem).limit(1))
        assert item is not None
        return item.public_id


def row_version(public_id: str) -> int:
    with SessionLocal() as db:
        token = db.scalar(
            select(RecurringItem.row_version).where(RecurringItem.public_id == public_id)
        )
        assert token is not None
        return token


def create_via_web(
    web_client: TestClient,
    *,
    merchant: str = "房租",
    amount: str = "6800",
    date_str: str = "2026-09-06",
    key: str | None = None,
):
    return web_client.post(
        "/web/recurring/create",
        data={
            "ledger_id": "owner",
            "merchant": merchant,
            "baseline_amount_yuan": amount,
            "next_expected_date": date_str,
            "idempotency_key": key or str(uuid4()),
        },
        follow_redirects=False,
    )


def edit_via_web(
    web_client: TestClient,
    public_id: str,
    *,
    merchant: str = "Cloud Storage 家庭版",
    amount: str = "25",
    date_str: str = "2026-10-08",
    token: int,
    key: str | None = None,
):
    return web_client.post(
        f"/web/recurring/{public_id}/edit",
        data={
            "ledger_id": "owner",
            "merchant": merchant,
            "baseline_amount_yuan": amount,
            "next_expected_date": date_str,
            "expected_row_version": str(token),
            "idempotency_key": key or str(uuid4()),
        },
        follow_redirects=False,
    )


def post_confirm(
    web_client: TestClient,
    *,
    merchant: str = "ChatGPT Plus",
    amount_cents: str = "20000",
    next_expected_date: str = "",
    **extra: str,
):
    """候选复核提交: 只带 merchant + amount 定位 + 可选日期 (provenance 服务端给)。"""
    return web_client.post(
        "/web/recurring/confirm-candidate",
        data={
            "ledger_id": "owner",
            "merchant": merchant,
            "amount_cents": amount_cents,
            "next_expected_date": next_expected_date,
            **extra,
        },
        follow_redirects=False,
    )


def extract_hidden_token(html: str, *, action: str) -> str:
    """Pull ``expected_row_version`` out of the form whose ``action`` matches —
    i.e. the token as actually rendered into the page, not a value read
    straight from the DB. Returns "" when absent so the caller can assert the
    page emits a real token."""
    form = re.search(re.escape(f'action="{action}"') + r".*?</form>", html, re.DOTALL)
    if not form:
        return ""
    field = re.search(r'name="expected_row_version"\s+value="([^"]*)"', form.group(0))
    return field.group(1) if field else ""


def hero_block(html: str) -> str:
    match = re.search(r'<section class="rc-hero".*?</section>', html, re.DOTALL)
    return match.group(0) if match else ""
