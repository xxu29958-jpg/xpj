from pydantic import BaseModel, ConfigDict, Field


class AccountProfileResponse(BaseModel):
    account_public_id: str
    display_name: str


class AccountProfileRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    expected_name: str = Field(min_length=1, max_length=120)
