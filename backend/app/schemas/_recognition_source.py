"""Optional source geometry addresses pixels, never a financial value."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RecognitionSourceLocation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_space: Literal["exif-transposed-pixels"]
    boxes: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]] = Field(min_length=1)


class RecognitionTextLine(BaseModel):
    text: str
    box: tuple[int, int, int, int]


class RecognitionTextLines(BaseModel):
    evidence_public_id: str
    image_sha256: str
    width: int
    height: int
    coordinate_space: Literal["exif-transposed-pixels"]
    lines: list[RecognitionTextLine]
