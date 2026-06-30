from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember, MerchantAlias, MerchantCatalog, RecurringItem
from app.services.merchant_service import normalize_merchant
from app.services.time_service import now_utc


def create_catalog(
    client: TestClient,
    headers: dict[str, str],
    *,
    display_name: str = "Starbucks",
    status: str = "active",
) -> dict:
    response = client.post(
        "/api/merchants/catalog",
        headers=headers,
        json={"display_name": display_name, "status": status},
    )
    assert response.status_code == 201, response.text
    return response.json()


def demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()


def seed_historical_expense(*, merchant: str = "Starbucks") -> None:
    with SessionLocal() as db:
        now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1800,
                merchant=merchant,
                category="Coffee",
                status="confirmed",
                expense_time=now,
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def assert_historical_expense_exists(*, merchant: str) -> None:
    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.merchant == merchant)
            .limit(1)
        )
        assert expense is not None


def seed_enabled_alias_target(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            MerchantAlias(
                tenant_id="owner",
                canonical_merchant="Anchor Store",
                canonical_key=merchant_key,
                alias="Anchor Alias",
                alias_key=normalize_merchant("Anchor Alias"),
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def disable_alias_and_seed_recurring(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        alias = db.scalar(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id == "owner")
            .where(MerchantAlias.canonical_key == merchant_key)
        )
        assert alias is not None
        alias.enabled = False
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key=merchant_key,
                merchant_name="Anchor Store",
                baseline_amount_cents=1800,
                last_amount_cents=1800,
                occurrence_count=3,
                status="active",
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        db.commit()


def archive_recurring(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        recurring = db.scalar(
            select(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
            .where(RecurringItem.merchant_key == merchant_key)
        )
        assert recurring is not None
        recurring.status = "archived"
        recurring.archived_at = now_utc()
        db.commit()


def bump_catalog_row_version(*, public_id: str) -> None:
    with SessionLocal() as db:
        item = db.scalar(
            select(MerchantCatalog)
            .where(MerchantCatalog.tenant_id == "owner")
            .where(MerchantCatalog.public_id == public_id)
            .limit(1)
        )
        assert item is not None
        item.row_version += 1
        item.updated_at = now_utc()
        db.commit()


def catalog_alias_by_key(*, alias_key: str) -> MerchantAlias | None:
    with SessionLocal() as db:
        return db.scalar(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id == "owner")
            .where(MerchantAlias.alias_key == alias_key)
            .limit(1)
        )


def seed_alias_key_conflict(*, alias: str) -> None:
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            MerchantAlias(
                tenant_id="owner",
                canonical_merchant="Other Store",
                canonical_key=normalize_merchant("Other Store"),
                alias=alias,
                alias_key=normalize_merchant(alias),
                enabled=False,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
