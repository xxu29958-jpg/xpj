"""Reports types and bucket dataclass (leaf)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.models import Expense
from app.services.money_projection_service import ProjectionGap

ReportGranularity = Literal["day", "week", "month"]
ReportRankingMetric = Literal["amount", "count"]


@dataclass(frozen=True)
class _TrendBucket:
    bucket: str
    label: str
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class _ProjectedEntry:
    entry_id: int
    root_expense_id: int
    entry_kind: str
    stream_date: date
    category: str
    merchant: str | None
    amount_cents: int | None
    gap: ProjectionGap | None


@dataclass(frozen=True)
class RankedExpense:
    expense: Expense
    amount_cents: int


@dataclass(frozen=True)
class ExpenseRanking:
    home_currency_code: str
    items: tuple[RankedExpense, ...]
    missing_rates: tuple[ProjectionGap, ...]
