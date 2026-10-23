from pydantic import BaseModel, ConfigDict, Field, StrictInt


class OcrRegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    box: list[StrictInt] = Field(min_length=4, max_length=4)
