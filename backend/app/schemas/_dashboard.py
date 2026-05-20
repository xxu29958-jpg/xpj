"""Dashboard card visibility / ordering payloads (cross-surface sync)."""

from __future__ import annotations

from pydantic import BaseModel, Field


__all__ = [
    "DashboardCardResponse",
    "DashboardCardUpdateRequest",
    "DashboardCardsResponse",
    "DashboardCardsUpdateRequest",
]


class DashboardCardResponse(BaseModel):
    key: str
    title: str
    visible: bool
    position: int


class DashboardCardsResponse(BaseModel):
    surface: str
    items: list[DashboardCardResponse]


class DashboardCardUpdateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    visible: bool = True
    position: int = Field(ge=0)


class DashboardCardsUpdateRequest(BaseModel):
    cards: list[DashboardCardUpdateRequest] = Field(default_factory=list)
