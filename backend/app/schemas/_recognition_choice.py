"""One deliberate time choice accompanying the existing financial command."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecognitionTimeChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_public_id: str = Field(min_length=1, max_length=36)
    candidate_id: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=64)
    source: Literal["image", "notification"]
    intent: Literal["candidate", "original_correction", "bookkeeping"] = "candidate"
    presentation: str | None = Field(default=None, max_length=64)
