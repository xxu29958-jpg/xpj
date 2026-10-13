"""Resolve one saved query, then read and project its current financial stream."""

from sqlalchemy.orm import Session

from app.schemas._saved_view import SavedViewResultRow, SavedViewResultsResponse
from app.services.expense_service import list_confirmed
from app.services.saved_view_service import resolve_view_query
from app.services.spending_contract_service import accounting_timezone_key
from app.services.spending_projection_service import project_confirmed_items


def read_saved_view_results(db: Session, *, tenant_id: str, actor_account_id: int,
                           public_id: str, page: int, page_size: int) -> SavedViewResultsResponse:
    conditions = resolve_view_query(db, tenant_id=tenant_id, actor_account_id=actor_account_id, public_id=public_id)
    items, total = list_confirmed(db, tenant_id=tenant_id, page=page, page_size=page_size,
        month=conditions.get("month"), category=conditions.get("category"), tag=conditions.get("tag"),
        query_text=conditions.get("q", ""), timezone_name=accounting_timezone_key(),
        missing_category=conditions.get("filter") == "missing_category",
        missing_accounting_date=conditions.get("filter") == "missing_accounting_date")
    projected = project_confirmed_items(db, tenant_id=tenant_id, home=conditions["home_currency_code"], items=items)
    return SavedViewResultsResponse(conditions=conditions, page=page, page_size=page_size, total=total,
        items=[SavedViewResultRow(entry=entry, projected_amount_cents=projection.amount_cents,
            projection_gap=projection.gap) for entry, projection in zip(items, projected, strict=True)])
