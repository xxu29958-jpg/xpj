"""Aggregate stats: category/tag totals, month index, monthly snapshot."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas._budget_advisor import ProjectionGapDto
from app.schemas._money import SignedMoneyAggregate

__all__ = [
    "CategoriesResponse",
    "CategoryStatsResponse",
    "MonthlyStatsResponse",
    "MonthsResponse",
    "TagStatsResponse",
    "TagsResponse",
]


class CategoryStatsResponse(BaseModel):
    category: str
    amount_cents: SignedMoneyAggregate | None
    count: int


class TagStatsResponse(BaseModel):
    tag: str
    amount_cents: SignedMoneyAggregate | None
    count: int


class CategoriesResponse(BaseModel):
    items: list[str]


class TagsResponse(BaseModel):
    items: list[str]


class MonthsResponse(BaseModel):
    items: list[str]


class MonthlyStatsResponse(BaseModel):
    month: str
    home_currency_code: str
    missing_rates: list[ProjectionGapDto]
    total_amount_cents: SignedMoneyAggregate | None
    count: int
    by_category: list[CategoryStatsResponse]
    by_tag: list[TagStatsResponse] = Field(default_factory=list)
