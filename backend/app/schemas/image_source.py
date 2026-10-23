"""Small, optional provenance carried by the original image upload command."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImageSourceTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Literal["exif_original", "exif_digitized", "exif_modified", "media_store_taken", "media_store_modified"]
    value: datetime
    precision: Literal["second", "millisecond"] = "second"


class ImageSourceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    original_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    upload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    orientation: int | None = Field(default=None, ge=1, le=8)
    original_width: int | None = Field(default=None, gt=0)
    original_height: int | None = Field(default=None, gt=0)
    transforms: list[Literal["orientation_applied", "resized", "transcoded"]] = Field(default_factory=list, max_length=3)
    times: list[ImageSourceTime] = Field(default_factory=list, max_length=5)
