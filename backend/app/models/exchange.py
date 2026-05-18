from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE, ECB_PROVIDER_BASE_CURRENCY, FX_SOURCE_ECB, FX_SOURCE_MANUAL
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "currency_code", "rate_date", name="uq_exchange_rates_tenant_currency_date"),
        CheckConstraint("rate_to_cny > 0", name="ck_exchange_rates_rate_positive"),
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
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate_to_cny: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default=FX_SOURCE_MANUAL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_exchange_rates_tenant_currency_date", ExchangeRate.tenant_id, ExchangeRate.currency_code, ExchangeRate.rate_date)


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
    home_currency_code: Mapped[str] = mapped_column(String(3), default=DEFAULT_HOME_CURRENCY_CODE, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate_to_home: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    provider_base_currency: Mapped[str] = mapped_column(String(3), default=ECB_PROVIDER_BASE_CURRENCY, nullable=False)
    provider_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_fx_rates_source_home_currency_date", FxRate.source, FxRate.home_currency_code, FxRate.currency_code, FxRate.rate_date)
