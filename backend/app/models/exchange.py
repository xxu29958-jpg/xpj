from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.fx_constants import ECB_PROVIDER_BASE_CURRENCY, FX_SOURCE_ECB, FX_SOURCE_MANUAL
from app.services.time_service import now_utc
from app.tenant_contract import DEFAULT_TENANT_ID


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "home_currency_code", "currency_code", "rate_date", name="uq_exchange_rates_tenant_pair_date"),
        CheckConstraint("rate_to_cny > 0", name="ck_exchange_rates_rate_positive"),
        CheckConstraint("row_version >= 1", name="ck_exchange_rates_row_version_positive"),
        CheckConstraint(
            "home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW') "
            "AND home_currency_code <> currency_code", name="ck_exchange_rates_home_currency",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_exchange_rates_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    # NULL is retained only for legacy rates awaiting the existing Owner adoption.
    home_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate_to_cny: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default=FX_SOURCE_MANUAL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)


Index("ix_exchange_rates_tenant_currency_date", ExchangeRate.tenant_id, ExchangeRate.currency_code, ExchangeRate.rate_date)

event.listen(
    ExchangeRate.__table__, "after_create",
    DDL("""
        CREATE OR REPLACE FUNCTION ticketbox_manual_rate_currency_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'manual exchange rate requires target currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (OLD.home_currency_code IS NOT NULL AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code)
                OR NEW.currency_code IS DISTINCT FROM OLD.currency_code
                OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.rate_date IS DISTINCT FROM OLD.rate_date
            ) THEN
                RAISE EXCEPTION 'manual exchange rate currency pair is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_manual_rate_currency
        BEFORE INSERT OR UPDATE ON exchange_rates
        FOR EACH ROW EXECUTE FUNCTION ticketbox_manual_rate_currency_guard();
    """).execute_if(dialect="postgresql"),
)


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "home_currency_code",
            "currency_code",
            "rate_date",
            name="uq_fx_rates_source_home_currency_date",
        ),
        CheckConstraint("rate_to_home > 0", name="ck_fx_rates_rate_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32), default=FX_SOURCE_ECB, nullable=False, index=True)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate_to_home: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    provider_base_currency: Mapped[str] = mapped_column(String(3), default=ECB_PROVIDER_BASE_CURRENCY, nullable=False)
    provider_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_fx_rates_source_home_currency_date", FxRate.source, FxRate.home_currency_code, FxRate.currency_code, FxRate.rate_date)
