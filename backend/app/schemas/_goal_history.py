"""Saved spending definitions exclude live spending, progress and FX projections."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.schemas._money import PositiveMoneyMinor
from app.services.time_service import to_iso


class GoalSnapshot(BaseModel):
    name: str
    goal_type: Literal["spending_limit"]
    period: Literal["monthly"]
    month: str
    category: str | None
    target_amount_cents: PositiveMoneyMinor
    home_currency_code: str | None
    status: Literal["active", "archived"]


class GoalRevisionResponse(BaseModel):
    row_version: int = Field(ge=1)
    change_kind: Literal["baseline", "create", "edit", "archive", "restore"]
    recorded_at: datetime
    snapshot: GoalSnapshot

    @field_serializer("recorded_at")
    def serialize_time(self, value: datetime) -> str:
        return to_iso(value)


class GoalHistoryResponse(BaseModel):
    ledger_id: str
    public_id: str
    items: list[GoalRevisionResponse]
    next_before_version: int | None
