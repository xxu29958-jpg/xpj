"""App consumers share the existing ledger saved-query and recorded-money owners."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._expense_stream import ConfirmedExpenseStreamItem
from app.schemas._money import SignedMoneyAggregate
from app.services.money_projection_service import ProjectionGap
from app.services.saved_view_service import SavedViewDetail


class SavedViewDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    month_mode: str
    month: str | None = None
    filter: str = ""
    tag_public_id: str | None = None
    home_currency_code: str
    query_text: str = Field(default="", max_length=80)
    category: str = Field(default="", max_length=64)


class SavedViewUpdateRequest(SavedViewDefinitionRequest):
    expected_row_version: int = Field(gt=0)


class SavedViewDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(gt=0)


class SavedViewListResponse(BaseModel):
    items: list[SavedViewDetail]


class SavedViewResultRow(BaseModel):
    entry: ConfirmedExpenseStreamItem
    projected_amount_cents: SignedMoneyAggregate | None
    projection_gap: ProjectionGap | None


class SavedViewResultsResponse(BaseModel):
    conditions: dict[str, str]
    items: list[SavedViewResultRow]
    page: int
    page_size: int
    total: int
