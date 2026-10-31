"""Original field candidates and explicit choices carried by the ordinary save."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._recognition_source import RecognitionSourceLocation


class RecognitionFieldChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["amount_cents", "merchant"]
    evidence_public_id: str = Field(min_length=1, max_length=36)
    candidate_id: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=64)
    source: Literal["image", "notification"] = "image"
    intent: Literal["candidate", "original_correction", "bookkeeping"] = "candidate"
    presentation: str | None = Field(default=None, max_length=64)


class RecognitionFieldCandidate(BaseModel):
    field: Literal["amount_cents", "merchant"]
    id: str
    value: int | str
    source_reading_value: int | str | None = Field(default=None, json_schema_extra={"readOnly": True},
        description="Bound source parser value before personal recall, in the same units as value. "
        "Null means unavailable; this is a parser reading, not independently verified original text.")
    label: str
    original_text: str
    explanation: str
    role: str
    event_id: str | None = None
    event_selected: bool = False
    currency_code: str | None = None
    minor_unit_exponent: int | None = None
    can_apply: bool
    evidence_public_id: str
    parser_version: str
    source: Literal["image", "notification"] = "image"
    selection_intent: Literal["candidate", "bookkeeping"] = "candidate"
    source_location: RecognitionSourceLocation | None = None
    presentation: str | None = None
