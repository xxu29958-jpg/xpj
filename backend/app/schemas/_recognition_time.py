"""Read-only time suggestions bound to an immutable image or notification source."""

from pydantic import BaseModel, Field


class RecognitionTimeCandidate(BaseModel):
    id: str
    label: str
    explanation: str
    original_text: str
    local_value: str
    precision: str
    source_timezone: str | None = None
    source_utc_offset_seconds: int | None = None
    can_apply: bool


class RecognitionTimeResponse(BaseModel):
    evidence_public_id: str
    source: str
    parser_version: str
    status: str
    candidates: list[RecognitionTimeCandidate] = Field(default_factory=list)
