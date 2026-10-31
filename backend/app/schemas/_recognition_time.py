"""Read-only time suggestions bound to an immutable image or notification source."""

from pydantic import BaseModel, Field

from app.schemas._recognition_source import RecognitionSourceLocation


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
    evidence_public_id: str | None = None
    source: str | None = None
    parser_version: str | None = None
    role: str = "unknown"
    components: dict[str, int] = Field(default_factory=dict)
    requires_year: bool = False
    event_id: str | None = None
    event_selected: bool = False
    source_location: RecognitionSourceLocation | None = None
    presentation: str | None = None


class RecognitionTimeResponse(BaseModel):
    evidence_public_id: str
    source: str
    parser_version: str
    status: str
    candidates: list[RecognitionTimeCandidate] = Field(default_factory=list)
