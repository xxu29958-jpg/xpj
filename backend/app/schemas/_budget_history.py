"""Budget history describes arrangements, never recalculated spending totals."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.schemas._budgets import BudgetCategoryRequest
from app.schemas._money import NonNegativeMoneyMinor, SignedMoneyMinor
from app.services.time_service import to_iso


class BudgetSnapshot(BaseModel):
    home_currency_code: str | None
    total_amount_cents: NonNegativeMoneyMinor
    non_monthly_amount_cents: NonNegativeMoneyMinor
    rollover_amount_cents: SignedMoneyMinor
    excluded_categories: list[str]
    category_budgets: list[BudgetCategoryRequest]
    archived: bool


class BudgetRevisionResponse(BaseModel):
    row_version: int = Field(ge=1)
    change_kind: Literal["baseline", "create", "edit", "archive", "restore"]
    recorded_at: datetime
    snapshot: BudgetSnapshot

    @field_serializer("recorded_at")
    def serialize_time(self, value: datetime) -> str:
        return to_iso(value)


class BudgetHistoryResponse(BaseModel):
    ledger_id: str
    month: str
    items: list[BudgetRevisionResponse]
    next_before_version: int | None
