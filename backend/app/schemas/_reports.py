"""Reports / lifestyle aggregations.

``LifestyleStatsResponse`` embeds an :class:`ExpenseResponse` (the user's
single largest expense for the month), which is the one cross-module
reference inside the schemas package — kept here rather than duplicated.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas._expense import ExpenseResponse

__all__ = [
    "LifestyleStatsResponse",
    "ReportCategoryComparisonResponse",
    "ReportMerchantRankingResponse",
    "ReportTrendPointResponse",
    "ReportsOverviewResponse",
]


class ReportTrendPointResponse(BaseModel):
    bucket: str
    label: str
    amount_cents: int
    count: int


class ReportMerchantRankingResponse(BaseModel):
    merchant: str
    amount_cents: int
    count: int


class ReportCategoryComparisonResponse(BaseModel):
    category: str
    amount_cents: int
    count: int
    previous_amount_cents: int
    previous_count: int
    delta_amount_cents: int
    delta_count: int
    year_over_year_amount_cents: int
    year_over_year_count: int
    year_over_year_delta_amount_cents: int
    year_over_year_delta_count: int


class ReportsOverviewResponse(BaseModel):
    month: str
    timezone: str
    granularity: str
    total_amount_cents: int
    count: int
    previous_month: str
    previous_total_amount_cents: int
    previous_count: int
    year_over_year_month: str
    year_over_year_total_amount_cents: int
    year_over_year_count: int
    year_over_year_delta_amount_cents: int
    year_over_year_delta_count: int
    merchant_category: str | None = None
    ranking_metric: str
    trend: list[ReportTrendPointResponse]
    merchant_ranking: list[ReportMerchantRankingResponse]
    category_comparison: list[ReportCategoryComparisonResponse]


class LifestyleStatsResponse(BaseModel):
    month: str
    ai_subscription_amount_cents: int
    digital_amount_cents: int
    max_expense: ExpenseResponse | None
    recent_7_days_amount_cents: int
    frequent_merchants: list[dict[str, int | str]]
    best_value_expenses: list[ExpenseResponse] = Field(default_factory=list)
    most_regretted_expenses: list[ExpenseResponse] = Field(default_factory=list)
