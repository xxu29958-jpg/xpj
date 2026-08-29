"""Legacy upload-money fixtures for the C07 migration round-trip tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.time_service import now_utc
from tests._infra.c07_money_migration import insert_legacy_expense, seed_owner


def seed_legacy_pending_upload_money() -> tuple[int, int, int]:
    """Seed pending and confirmed source facts without adding later schema."""

    seed_owner()
    now = now_utc()
    pending_home_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=1_234,
        home_currency_code="CNY",
        original_currency_code="CNY",
        original_amount_minor=1_234,
        exchange_rate_to_cny=Decimal("1"),
        exchange_rate_date=date(2026, 7, 20),
        exchange_rate_source="base",
        fx_status="ready",
        merchant="legacy pending upload",
        category="餐饮",
        source="iPhone截图",
        image_path="uploads/legacy-pending.png",
        raw_text="legacy text",
        confidence=0.9,
        ocr_draft_fields=(
            '["original_amount", "original_currency", '
            '"exchange_rate_to_cny", "spent_at", "merchant"]'
        ),
        status="pending",
        created_at=now,
        updated_at=now,
        row_version=7,
    )
    confirmed_home_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=2_345,
        home_currency_code="CNY",
        original_currency_code="CNY",
        original_amount_minor=2_345,
        exchange_rate_to_cny=Decimal("1"),
        exchange_rate_date=date(2026, 7, 20),
        exchange_rate_source="base",
        fx_status="ready",
        merchant="confirmed upload",
        source="iPhone截图",
        image_path="uploads/confirmed.png",
        status="confirmed",
        created_at=now,
        updated_at=now,
        confirmed_at=now,
    )
    pending_foreign_id = insert_legacy_expense(
        tenant_id="owner",
        amount_cents=7_000,
        home_currency_code="CNY",
        original_currency_code="USD",
        original_amount_minor=1_000,
        exchange_rate_to_cny=Decimal("7"),
        exchange_rate_date=date(2026, 7, 20),
        exchange_rate_source="manual",
        fx_status="ready",
        merchant="reviewed foreign upload",
        source="iPhone截图",
        image_path="uploads/foreign.png",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    return pending_home_id, confirmed_home_id, pending_foreign_id
