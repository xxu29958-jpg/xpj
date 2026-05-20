"""Aggregate stats: category/tag totals, month index, monthly snapshot."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    amount_cents: int
    count: int


class TagStatsResponse(BaseModel):
    tag: str
    amount_cents: int
    count: int


class CategoriesResponse(BaseModel):
    items: list[str]


class TagsResponse(BaseModel):
    items: list[str]


class MonthsResponse(BaseModel):
    items: list[str]


class MonthlyStatsResponse(BaseModel):
    month: str
    total_amount_cents: int
    count: int
    by_category: list[CategoryStatsResponse]
    by_tag: list[TagStatsResponse] = Field(default_factory=list)
