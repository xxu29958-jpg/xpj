"""Explicit pixel feedback is independent of candidates and financial values."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OriginalTextFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    field: Literal["amount_cents", "merchant", "expense_time", "original_currency_code", "transaction_kind"]
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_space: Literal["exif-transposed-pixels"] = "exif-transposed-pixels"
    location_state: Literal["unlocated", "coarse_point", "suggested_region", "verified_region"] = "unlocated"
    point: tuple[float, float] | None = None
    box: tuple[float, float, float, float] | None = None
    verbatim_text: str = Field(default="", max_length=2000)
    role: str = Field(min_length=1, max_length=64)
    issue: Literal["transcription", "missing", "unreadable", "cropped", "absent"] = "transcription"
    text_verified: bool = False
    evidence_public_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def location_and_transcription(self):
        if (self.location_state == "coarse_point") != (self.point is not None):
            raise ValueError("only a coarse location carries a point")
        if (self.location_state in {"suggested_region", "verified_region"}) != (self.box is not None):
            raise ValueError("a region requires its original pixel rectangle")
        if self.point is not None and not (0 <= self.point[0] <= self.width and 0 <= self.point[1] <= self.height):
            raise ValueError("point is outside the original")
        if self.box is not None:
            left, top, right, bottom = self.box
            if not (0 <= left < right <= self.width and 0 <= top < bottom <= self.height):
                raise ValueError("region is outside the original")
        if self.issue in {"unreadable", "cropped", "absent"}:
            if self.verbatim_text.strip() or self.text_verified:
                raise ValueError("unreadable or absent text cannot supply a transcription")
        elif not self.verbatim_text.strip():
            raise ValueError("an original correction requires its actual text")
        return self
