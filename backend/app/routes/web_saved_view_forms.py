"""Raw saved-query inputs stay intact until an explicit review or accepted receipt."""

from pydantic import BaseModel

from app.errors import AppError


class SavedViewDefinitionForm(BaseModel):
    ledger_id: str = ""
    public_id: str = ""
    name: str = ""
    month_mode: str = "current"
    month: str = ""
    filter: str = ""
    tag_public_id: str = ""
    home_currency_code: str = ""
    query_text: str = ""
    category: str = ""
    idempotency_key: str = ""
    draft_ref: str = ""
    draft_scope: str = ""
    review_new: bool = False
    review_latest: bool = False


class SavedViewForm(SavedViewDefinitionForm):
    expected_row_version: str = ""


def saved_view_refusal(exc: AppError) -> str:
    return "rejected" if exc.error in {"state_conflict", "invalid_request", "invalid_currency_code",
        "saved_view_conflict", "saved_view_not_found", "saved_view_tag_repair_required",
        "idempotency_key_required", "idempotency_key_reused"} else "blocked"
