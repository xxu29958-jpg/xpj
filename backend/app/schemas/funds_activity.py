"""A reviewed reversal of one actual income, transfer or loan event."""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import SignedMoneyMinor


class ActivityCorrectionPart(BaseModel):
    account_public_id: str
    account_row_version: int
    account_name: str
    currency_code: str
    amount_minor: SignedMoneyMinor


class AccountActivityVoid(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_row_version: int = Field(ge=1)
    event_public_id: str = Field(min_length=1, max_length=36)
    account_row_versions: dict[str, Annotated[int, Field(ge=1)]] = Field(min_length=1, max_length=8)
    occurred_on: date
    reason: str = Field(min_length=1, max_length=255)
