"""Original field candidates and explicit choices carried by the ordinary save."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecognitionFieldChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["amount_cents", "merchant"]
    evidence_public_id: str = Field(min_length=1, max_length=36)
    candidate_id: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=64)
    source: Literal["image"] = "image"
    intent: Literal["candidate", "original_correction", "bookkeeping"] = "candidate"


class RecognitionFieldCandidate(BaseModel):
    field: Literal["amount_cents", "merchant"]
    id: str
    value: int | str
    label: str
    original_text: str
    explanation: str
    role: str
    event_id: str | None = None
    currency_code: str | None = None
    minor_unit_exponent: int | None = None
    can_apply: bool
    evidence_public_id: str
    parser_version: str
    source: Literal["image"] = "image"
    selection_intent: Literal["candidate", "bookkeeping"] = "candidate"
